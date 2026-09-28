/**
 * Configuration for Playwright using default from @jupyterlab/galata
 */
const fs = require('fs');
const path = require('path');
const baseConfig = require('@jupyterlab/galata/lib/playwright-config');

// A developer lab often holds 8888; JUPYTER_TEST_PORT moves the test server off it.
const PORT = process.env.JUPYTER_TEST_PORT || '8888';
const BASE_URL = `http://localhost:${PORT}`;

// The FIFO the test server writes to. Set here so the server (jupyter_server_test_config.py)
// and the specs agree on one path; the specs create the FIFO, playing the reader's role.
process.env.VOICE_TEST_SINK =
  process.env.VOICE_TEST_SINK ||
  path.join(__dirname, '.tmp-voice', 'pulseaudio.fifo');
fs.mkdirSync(path.dirname(process.env.VOICE_TEST_SINK), { recursive: true });

module.exports = {
  ...baseConfig,
  // Specs share the server's single producer and the FIFO, so they must not overlap.
  workers: 1,
  fullyParallel: false,
  use: {
    ...baseConfig.use,
    baseURL: BASE_URL,
    launchOptions: {
      // A fake microphone, granted without a prompt.
      args: [
        '--use-fake-ui-for-media-stream',
        '--use-fake-device-for-media-stream'
      ]
    }
  },
  webServer: {
    command: 'jlpm start',
    url: `${BASE_URL}/lab`,
    timeout: 120 * 1000,
    // Never adopt a server this suite did not start: it would drive a real session.
    reuseExistingServer: false
  }
};
