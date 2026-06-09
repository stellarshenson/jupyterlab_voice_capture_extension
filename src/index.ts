import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { requestAPI } from './request';

/**
 * Initialization data for the jupyterlab_voice_capture_extension extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyterlab_voice_capture_extension:plugin',
  description: 'JupyterLab extension that captures microphone audio in the browser and streams it to a server-side bridge, exposing it as a virtual audio source so terminal applications running in the container (such as Claude Code voice mode) can record from the user\'s microphone',
  autoStart: true,
  activate: (app: JupyterFrontEnd) => {
    console.log('JupyterLab extension jupyterlab_voice_capture_extension is activated!');

    requestAPI<any>('hello', app.serviceManager.serverSettings)
      .then(data => {
        console.log(data);
      })
      .catch(reason => {
        console.error(
          `The jupyterlab_voice_capture_extension server extension appears to be missing.\n${reason}`
        );
      });
  }
};

export default plugin;
