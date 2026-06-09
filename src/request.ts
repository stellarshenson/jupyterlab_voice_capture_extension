import { URLExt } from '@jupyterlab/coreutils';

import { ServerConnection } from '@jupyterlab/services';

/**
 * Build the websocket URL for the voice-capture stream endpoint.
 *
 * The endpoint lives under the Jupyter base URL and inherits Jupyter token auth - the
 * token is passed as a query parameter because the WebSocket constructor cannot set
 * Authorization headers.
 */
export function voiceCaptureWsUrl(
  serverSettings: ServerConnection.ISettings
): string {
  let url = URLExt.join(
    serverSettings.wsUrl,
    'jupyterlab-voice-capture-extension', // our server extension's API namespace
    'stream'
  );
  if (serverSettings.token) {
    url += `?token=${encodeURIComponent(serverSettings.token)}`;
  }
  return url;
}
