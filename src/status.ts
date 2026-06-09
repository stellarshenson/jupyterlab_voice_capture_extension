import { LabIcon } from '@jupyterlab/ui-components';

import { Widget } from '@lumino/widgets';

import { VoiceCapture, VoiceCaptureState } from './voice-capture';

const MIC_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
  <path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3z"/>
  <path d="M19 11a7 7 0 0 1-6 6.92V21h-2v-3.08A7 7 0 0 1 5 11h2a5 5 0 0 0 10 0h2z"/>
</svg>`;

export const micIcon = new LabIcon({
  name: 'voice-capture:mic',
  svgstr: MIC_SVG
});

const LABELS: Record<VoiceCaptureState, string> = {
  idle: 'Disconnected',
  connecting: 'Connecting',
  streaming: 'Connected',
  error: 'Error'
};

const TITLES: Record<VoiceCaptureState, string> = {
  idle: 'Voice capture off - click to start',
  connecting: 'Voice capture connecting...',
  streaming: 'Voice capture on - streaming to server',
  error: 'Voice capture error'
};

/**
 * Status-bar control: a microphone icon plus a status label, reflecting exactly one of
 * idle / connecting / streaming / error (A4). The icon animates per state - the streaming
 * state pulses faint red with a glow, the error state blinks orange (see base.css).
 */
export class VoiceStatus extends Widget {
  constructor(model: VoiceCapture) {
    super();
    this._model = model;
    this.addClass('jp-VoiceCapture-status');

    const icon = document.createElement('span');
    icon.className = 'jp-VoiceCapture-icon';
    micIcon.element({ container: icon });

    this._label = document.createElement('span');
    this._label.className = 'jp-VoiceCapture-label';

    this.node.appendChild(icon);
    this.node.appendChild(this._label);
    this.node.addEventListener('click', this._onClick);

    model.stateChanged.connect(this._refresh, this);
    this._refresh();
  }

  dispose(): void {
    this.node.removeEventListener('click', this._onClick);
    this._model.stateChanged.disconnect(this._refresh, this);
    super.dispose();
  }

  private _onClick = (): void => {
    this._model.toggle();
  };

  private _refresh(): void {
    const state = this._model.state;
    this.removeClass('jp-mod-idle');
    this.removeClass('jp-mod-connecting');
    this.removeClass('jp-mod-streaming');
    this.removeClass('jp-mod-error');
    this.addClass(`jp-mod-${state}`);
    this.node.dataset.vcState = state;
    this._label.textContent = LABELS[state];
    this.node.title =
      state === 'error' ? this._model.message || TITLES.error : TITLES[state];
  }

  private _label: HTMLSpanElement;
  private _model: VoiceCapture;
}
