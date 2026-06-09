import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { ICommandPalette } from '@jupyterlab/apputils';

import { IStatusBar } from '@jupyterlab/statusbar';

import { VoiceCapture } from './voice-capture';

import { VoiceStatus } from './status';

const TOGGLE_COMMAND = 'voice-capture:toggle';

/**
 * Initialization data for the jupyterlab_voice_capture_extension extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyterlab_voice_capture_extension:plugin',
  description:
    "JupyterLab extension that captures microphone audio in the browser and streams it to a server-side bridge, exposing it as a virtual audio source so terminal applications running in the container (such as Claude Code voice mode) can record from the user's microphone",
  autoStart: true,
  optional: [ICommandPalette, IStatusBar],
  activate: (
    app: JupyterFrontEnd,
    palette: ICommandPalette | null,
    statusBar: IStatusBar | null
  ) => {
    console.log(
      'JupyterLab extension jupyterlab_voice_capture_extension is activated!'
    );

    const model = new VoiceCapture(app.serviceManager.serverSettings);

    app.commands.addCommand(TOGGLE_COMMAND, {
      label: 'Toggle Voice Capture',
      isToggled: () => model.enabled,
      execute: () => model.toggle()
    });

    if (palette) {
      palette.addItem({ command: TOGGLE_COMMAND, category: 'Voice Capture' });
    }

    if (statusBar) {
      statusBar.registerStatusItem(
        'jupyterlab_voice_capture_extension:status',
        {
          item: new VoiceStatus(model),
          align: 'right',
          rank: 100
        }
      );
    }
  }
};

export default plugin;
