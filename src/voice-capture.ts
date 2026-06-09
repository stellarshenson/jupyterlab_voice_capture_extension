import { ServerConnection } from '@jupyterlab/services';

import { ISignal, Signal } from '@lumino/signaling';

import { voiceCaptureWsUrl } from './request';

import { WORKLET_PROCESSOR_NAME, workletModuleUrl } from './worklet';

/**
 * The control reflects exactly one of these at all times (A4). `idle` = not capturing
 * (Off), `connecting` = capture on but the websocket is not open yet - initial connect or
 * auto-reconnect (Connecting), `streaming` = capturing and frames flowing (Connected),
 * `error` = a blocking failure (denied permission, missing device, insecure context) that
 * turned capture off. `error` carries a human-readable message.
 */
export type VoiceCaptureState = 'idle' | 'connecting' | 'streaming' | 'error';

const BASE_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 10000;

/**
 * Owns the browser capture pipeline and its lifecycle: getUserMedia, the 16 kHz
 * AudioContext + worklet, the websocket to the server bridge, reconnect, and teardown.
 */
export class VoiceCapture {
  constructor(serverSettings: ServerConnection.ISettings) {
    this._serverSettings = serverSettings;
    this._unloadHandler = () => this.disable();
    window.addEventListener('beforeunload', this._unloadHandler);
  }

  get state(): VoiceCaptureState {
    return this._state;
  }

  get message(): string {
    return this._message;
  }

  /** Whether the user has turned capture on (independent of momentary connection state). */
  get enabled(): boolean {
    return this._enabled;
  }

  get stateChanged(): ISignal<this, VoiceCaptureState> {
    return this._stateChanged;
  }

  toggle(): void {
    if (this._enabled) {
      this.disable();
    } else {
      void this.enable();
    }
  }

  async enable(): Promise<void> {
    if (this._enabled) {
      return;
    }
    // E3: getUserMedia is only available in a secure context.
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      this._setError(
        'Microphone capture requires a secure context (https or localhost).'
      );
      return;
    }
    this._enabled = true;
    this._setState('connecting', ''); // shown while the permission prompt / connect runs
    try {
      this._stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      this._enabled = false;
      this._handleGetUserMediaError(err);
      return;
    }
    try {
      await this._startAudioGraph();
    } catch (err) {
      this._enabled = false;
      this._teardownAudio();
      this._setError(`Failed to start audio capture: ${String(err)}`);
      return;
    }
    this._connect();
  }

  disable(): void {
    this._enabled = false;
    this._clearReconnect();
    this._closeSocket();
    this._teardownAudio();
    this._setState('idle', '');
  }

  dispose(): void {
    window.removeEventListener('beforeunload', this._unloadHandler);
    this.disable();
  }

  // -- audio graph ------------------------------------------------------------------

  private async _startAudioGraph(): Promise<void> {
    const ctx = new AudioContext({ sampleRate: 16000 }); // B1: browser resamples to 16 kHz
    this._audioContext = ctx;
    const url = workletModuleUrl();
    try {
      await ctx.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    const source = ctx.createMediaStreamSource(this._stream!);
    const node = new AudioWorkletNode(ctx, WORKLET_PROCESSOR_NAME);
    node.port.onmessage = (ev: MessageEvent) => {
      const ws = this._ws;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(ev.data as ArrayBuffer); // binary frame (B4)
      }
    };
    source.connect(node);
    // Deliberately not connected to ctx.destination - we don't play the mic back.
    this._source = source;
    this._workletNode = node;
  }

  private _teardownAudio(): void {
    if (this._workletNode) {
      this._workletNode.port.onmessage = null;
      try {
        this._workletNode.disconnect();
      } catch {
        /* already disconnected */
      }
      this._workletNode = null;
    }
    if (this._source) {
      try {
        this._source.disconnect();
      } catch {
        /* already disconnected */
      }
      this._source = null;
    }
    if (this._stream) {
      this._stream.getTracks().forEach(track => track.stop()); // A3: release the mic
      this._stream = null;
    }
    if (this._audioContext) {
      void this._audioContext.close(); // A3: clears the browser mic indicator
      this._audioContext = null;
    }
  }

  // -- websocket --------------------------------------------------------------------

  private _connect(): void {
    this._setState('connecting', '');
    let ws: WebSocket;
    try {
      ws = new WebSocket(voiceCaptureWsUrl(this._serverSettings));
    } catch (err) {
      this._scheduleReconnect();
      return;
    }
    ws.binaryType = 'arraybuffer';
    this._ws = ws;
    ws.onopen = () => {
      this._backoff = BASE_BACKOFF_MS;
      this._setState('streaming', '');
    };
    ws.onclose = () => {
      this._ws = null;
      if (!this._enabled) {
        return;
      }
      // E4 / D1: unreachable or dropped while enabled -> back to connecting, retry with
      // backoff. Auto-recovers to streaming once the server bridge is reachable.
      this._setState('connecting', '');
      this._scheduleReconnect();
    };
  }

  private _closeSocket(): void {
    const ws = this._ws;
    this._ws = null;
    if (ws) {
      ws.onopen = null;
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;
      try {
        ws.close();
      } catch {
        /* already closing */
      }
    }
  }

  private _scheduleReconnect(): void {
    if (this._reconnectTimer !== null) {
      window.clearTimeout(this._reconnectTimer);
    }
    const delay = this._backoff;
    this._backoff = Math.min(this._backoff * 2, MAX_BACKOFF_MS);
    this._reconnectTimer = window.setTimeout(() => {
      this._reconnectTimer = null;
      if (this._enabled) {
        this._connect();
      }
    }, delay);
  }

  private _clearReconnect(): void {
    if (this._reconnectTimer !== null) {
      window.clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    this._backoff = BASE_BACKOFF_MS;
  }

  // -- errors / state ---------------------------------------------------------------

  private _handleGetUserMediaError(err: unknown): void {
    const name = (err as DOMException)?.name;
    if (name === 'NotAllowedError' || name === 'SecurityError') {
      this._setError('Microphone permission denied.'); // E1: safe off state, no retry storm
    } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
      this._setError('No microphone input device found.'); // E2: distinct from a denial
    } else {
      this._setError(`Could not access the microphone: ${String(err)}`);
    }
  }

  private _setError(message: string): void {
    this._setState('error', message);
  }

  private _setState(state: VoiceCaptureState, message: string): void {
    this._state = state;
    this._message = message;
    this._stateChanged.emit(state);
  }

  private readonly _serverSettings: ServerConnection.ISettings;
  private readonly _unloadHandler: () => void;
  private readonly _stateChanged = new Signal<this, VoiceCaptureState>(this);

  private _state: VoiceCaptureState = 'idle';
  private _message = '';
  private _enabled = false;

  private _stream: MediaStream | null = null;
  private _audioContext: AudioContext | null = null;
  private _source: MediaStreamAudioSourceNode | null = null;
  private _workletNode: AudioWorkletNode | null = null;
  private _ws: WebSocket | null = null;

  private _reconnectTimer: number | null = null;
  private _backoff = BASE_BACKOFF_MS;
}
