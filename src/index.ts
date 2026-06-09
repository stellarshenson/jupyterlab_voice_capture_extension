import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { ICommandPalette } from '@jupyterlab/apputils';

import { ISettingRegistry } from '@jupyterlab/settingregistry';

import { IStatusBar } from '@jupyterlab/statusbar';

import { VoiceCapture } from './voice-capture';

import { VoiceStatus } from './status';

const PLUGIN_ID = 'jupyterlab_voice_capture_extension:plugin';
const TOGGLE_COMMAND = 'voice-capture:toggle';

/**
 * Initialization data for the jupyterlab_voice_capture_extension extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: PLUGIN_ID,
  description:
    "JupyterLab extension that captures microphone audio in the browser and streams it to a server-side bridge, exposing it as a virtual audio source so terminal applications running in the container (such as Claude Code voice mode) can record from the user's microphone",
  autoStart: true,
  optional: [ICommandPalette, IStatusBar, ISettingRegistry],
  activate: (
    app: JupyterFrontEnd,
    palette: ICommandPalette | null,
    statusBar: IStatusBar | null,
    settingRegistry: ISettingRegistry | null
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
          align: 'left',
          rank: 100
        }
      );
    }

    if (settingRegistry) {
      settingRegistry
        .load(PLUGIN_ID)
        .then(settings => {
          // Auto-connect on startup only when the user has opted in (default off).
          if (settings.get('autoConnect').composite === true) {
            void model.enable();
          }
        })
        .catch(reason => {
          console.error(
            'Failed to load jupyterlab_voice_capture_extension settings.',
            reason
          );
        });
    }
  }
};

export default plugin;
