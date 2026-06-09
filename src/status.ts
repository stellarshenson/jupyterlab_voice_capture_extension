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

const TITLES: Record<VoiceCaptureState, string> = {
  idle: 'Voice capture off - click to start',
  streaming: 'Voice capture on - streaming to server',
  error: 'Voice capture error'
};

/**
 * Status-bar control: a microphone icon that toggles capture and reflects exactly one of
 * idle / streaming / error (A4). The streaming state pulses faint red (see base.css).
 */
export class VoiceStatus extends Widget {
  constructor(model: VoiceCapture) {
    super();
    this._model = model;
    this.addClass('jp-VoiceCapture-status');
    micIcon.element({ container: this.node });
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
    this.removeClass('jp-mod-streaming');
    this.removeClass('jp-mod-error');
    this.addClass(`jp-mod-${state}`);
    this.node.dataset.vcState = state;
    this.node.title =
      state === 'error' ? this._model.message || TITLES.error : TITLES[state];
  }

  private _model: VoiceCapture;
}
