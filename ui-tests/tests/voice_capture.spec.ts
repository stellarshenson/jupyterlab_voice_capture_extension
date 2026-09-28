import { expect, test } from '@jupyterlab/galata';
import type { Page } from '@playwright/test';
import { ChildProcess, spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Functional tests: a real JupyterLab, a real browser with Chromium's fake microphone, the
 * real server handler, and a FIFO read by fifo_reader.py in place of PulseAudio. Ids in
 * the test titles are the criteria in docs/acc-crit-voice-capture.md.
 */

const SINK = process.env.VOICE_TEST_SINK as string;
const STATUS = '.jp-VoiceCapture-status';
const ICON = '.jp-VoiceCapture-icon';
const BYTES_PER_SECOND = 16000 * 2; // 16 kHz, mono, 2 bytes per sample

test.use({ autoGoto: false });

/** Runs in the page before the app loads: records what the extension asks of the browser. */
function instrument(options: { denyMic?: boolean }): void {
  const w = window as any;
  const vc: any = { gum: 0, streams: [], sockets: [], frames: {} };
  w.__vc = vc;
  const md = navigator.mediaDevices;
  const getUserMedia = md.getUserMedia.bind(md);
  md.getUserMedia = async (constraints?: MediaStreamConstraints) => {
    vc.gum++;
    if (options.denyMic) {
      throw new DOMException('denied', 'NotAllowedError');
    }
    const stream = await getUserMedia(constraints);
    vc.streams.push(stream);
    return stream;
  };
  const NativeWebSocket = window.WebSocket;
  w.WebSocket = class extends NativeWebSocket {
    constructor(url: string | URL, protocols?: string | string[]) {
      super(url, protocols);
      if (!String(url).includes('jupyterlab-voice-capture-extension/stream')) {
        return;
      }
      vc.sockets.push(this);
      const send = this.send.bind(this);
      this.send = (data: any) => {
        const key = `${data.constructor.name}:${data.byteLength}`;
        vc.frames[key] = (vc.frames[key] || 0) + 1;
        send(data);
      };
    }
  };
}

interface IRecord {
  gum: number;
  sockets: number;
  liveTracks: number;
  frames: Record<string, number>;
}

async function record(page: Page): Promise<IRecord> {
  return page.evaluate(() => {
    const vc = (window as any).__vc;
    const tracks = vc.streams.flatMap((s: MediaStream) => s.getTracks());
    return {
      gum: vc.gum,
      sockets: vc.sockets.length,
      liveTracks: tracks.filter(
        (t: MediaStreamTrack) => t.readyState === 'live'
      ).length,
      frames: vc.frames
    };
  });
}

async function openLab(
  page: Page,
  url: string,
  options: { denyMic?: boolean } = {}
): Promise<void> {
  await page.addInitScript(instrument, options);
  await page.goto(url);
  await page.locator(STATUS).waitFor();
}

async function animation(page: Page): Promise<string> {
  return page
    .locator(`${STATUS} ${ICON}`)
    .evaluate(el => getComputedStyle(el).animationName);
}

interface ISample {
  t: number;
  bytes: number;
  peak: number;
}

/** The FIFO's reader, standing in for PulseAudio's module-pipe-source. */
class FifoReader {
  static async start(): Promise<FifoReader> {
    const reader = new FifoReader();
    await expect
      .poll(() => fs.existsSync(SINK) && fs.statSync(SINK).isFIFO(), {
        timeout: 10000
      })
      .toBe(true);
    return reader;
  }

  private constructor() {
    this._child = spawn(process.env.PYTHON || 'python3', [
      path.join(__dirname, 'fifo_reader.py'),
      SINK
    ]);
    this._child.on('error', e => (this._error = `spawn failed: ${e}`));
    let pending = '';
    this._child.stdout!.on('data', chunk => {
      pending += chunk;
      const lines = pending.split('\n');
      pending = lines.pop() as string;
      for (const line of lines) {
        this._last = JSON.parse(line);
      }
    });
  }

  last(): ISample {
    if (this._error) {
      throw new Error(this._error);
    }
    return this._last;
  }

  /** Bytes per second over `ms` of wall time. */
  async rate(page: Page, ms: number): Promise<number> {
    const a = this.last();
    await page.waitForTimeout(ms);
    const b = this.last();
    return (b.bytes - a.bytes) / (b.t - a.t);
  }

  /**
   * Waits for one `ms` window whose byte rate satisfies `ok`. A busy main thread holds
   * websocket sends back and releases them in a burst, so a single window can read low
   * during the stall and high after it.
   */
  async waitForRate(
    page: Page,
    ok: (rate: number) => boolean,
    ms: number
  ): Promise<void> {
    await expect
      .poll(async () => ok(await this.rate(page, ms)), {
        timeout: 30000,
        intervals: [0]
      })
      .toBe(true);
  }

  async waitForBytes(n: number): Promise<void> {
    await expect
      .poll(() => this.last().bytes, { timeout: 10000 })
      .toBeGreaterThan(n);
  }

  async stop(): Promise<void> {
    const exited = new Promise(resolve => this._child.on('close', resolve));
    this._child.kill('SIGTERM');
    await exited;
  }

  private _child: ChildProcess;
  private _error = '';
  private _last: ISample = { t: 0, bytes: 0, peak: 0 };
}

test.describe('voice capture', () => {
  let reader: FifoReader;

  test.beforeEach(async () => {
    reader = await FifoReader.start();
  });

  test.afterEach(async () => {
    await reader.stop();
  });

  test('A1: captures nothing until the user turns it on', async ({
    page,
    baseURL
  }) => {
    await openLab(page, `${baseURL}/lab`);
    const status = page.locator(STATUS);
    await expect(status).toHaveAttribute('data-vc-state', 'idle');
    await expect(status).toHaveText('Disconnected');
    expect(await animation(page)).toBe('none');

    await page.waitForTimeout(1000);
    expect((await record(page)).gum).toBe(0);
    expect(reader.last().bytes).toBe(0);

    await status.click();
    await expect.poll(async () => (await record(page)).gum).toBe(1);
  });

  test('A2/B1/B3/B4/C2: streams 16 kHz mono s16le in 640-byte binary frames to the FIFO', async ({
    page,
    baseURL
  }) => {
    await openLab(page, `${baseURL}/lab`);
    const status = page.locator(STATUS);
    await status.click();
    await expect(status).toHaveAttribute('data-vc-state', 'streaming', {
      timeout: 15000
    });
    await expect(status).toHaveText('Connected');
    expect(await animation(page)).toBe('vc-pulse');
    expect((await record(page)).liveTracks).toBe(1);

    await reader.waitForRate(
      page,
      rate => Math.abs(rate - BYTES_PER_SECOND) < BYTES_PER_SECOND * 0.15,
      3000
    );
    expect(reader.last().peak).toBeGreaterThan(1000); // the fake microphone's tone, not silence
    expect(Object.keys((await record(page)).frames)).toEqual([
      'ArrayBuffer:640'
    ]);
  });

  test('A3: a second click stops capture, releases the microphone and the FIFO goes quiet', async ({
    page,
    baseURL
  }) => {
    await openLab(page, `${baseURL}/lab`);
    const status = page.locator(STATUS);
    await status.click();
    await expect(status).toHaveAttribute('data-vc-state', 'streaming', {
      timeout: 15000
    });
    await reader.waitForBytes(BYTES_PER_SECOND / 2);

    await status.click();
    await expect(status).toHaveAttribute('data-vc-state', 'idle');
    await expect(status).toHaveText('Disconnected');
    await expect
      .poll(async () => (await record(page)).liveTracks, { timeout: 1000 })
      .toBe(0);
    await reader.waitForRate(page, rate => rate === 0, 1000);
  });

  test('E1: a denied microphone shows Error, and a click disconnects without retrying', async ({
    page,
    baseURL
  }) => {
    await openLab(page, `${baseURL}/lab`, { denyMic: true });
    const status = page.locator(STATUS);
    await status.click();
    await expect(status).toHaveAttribute('data-vc-state', 'error');
    await expect(status).toHaveText('Error');
    await expect(status).toHaveAttribute(
      'title',
      'Microphone permission denied.'
    );
    expect(await animation(page)).toBe('vc-blink');

    await status.click();
    await expect(status).toHaveAttribute('data-vc-state', 'idle');
    await expect(status).toHaveText('Disconnected');
    await page.waitForTimeout(1000);
    expect((await record(page)).gum).toBe(1);
  });

  test('D1: reconnects after the connection drops and keeps capture on', async ({
    page,
    baseURL
  }) => {
    await openLab(page, `${baseURL}/lab`);
    const status = page.locator(STATUS);
    await status.click();
    await expect(status).toHaveAttribute('data-vc-state', 'streaming', {
      timeout: 15000
    });

    await page.evaluate(() => (window as any).__vc.sockets.at(-1).close());
    await expect
      .poll(async () => (await record(page)).sockets, { timeout: 15000 })
      .toBe(2);
    await expect(status).toHaveAttribute('data-vc-state', 'streaming', {
      timeout: 15000
    });
    expect((await record(page)).liveTracks).toBe(1);
    await reader.waitForBytes(BYTES_PER_SECOND / 2);
  });

  test('D2: closing the tab stops the stream into the FIFO', async ({
    page,
    baseURL
  }) => {
    const tab = await page.context().newPage();
    await openLab(tab, `${baseURL}/lab`);
    const status = tab.locator(STATUS);
    await status.click();
    await expect(status).toHaveAttribute('data-vc-state', 'streaming', {
      timeout: 15000
    });
    await reader.waitForBytes(BYTES_PER_SECOND / 2);

    await tab.close({ runBeforeUnload: true });
    await reader.waitForRate(page, rate => rate === 0, 1000);
  });

  test('D3: a second tab takes over and the first tab stays stopped', async ({
    page,
    baseURL
  }) => {
    await openLab(page, `${baseURL}/lab`);
    const first = page.locator(STATUS);
    await first.click();
    await expect(first).toHaveAttribute('data-vc-state', 'streaming', {
      timeout: 15000
    });

    const tab = await page.context().newPage();
    await openLab(tab, `${baseURL}/lab`);
    const second = tab.locator(STATUS);
    await second.click();
    await expect(second).toHaveAttribute('data-vc-state', 'streaming', {
      timeout: 15000
    });

    await expect(first).toHaveAttribute('data-vc-state', 'idle', {
      timeout: 5000
    });
    await tab.waitForTimeout(3000);
    await expect(first).toHaveAttribute('data-vc-state', 'idle');
    await expect(second).toHaveAttribute('data-vc-state', 'streaming');
    expect((await record(tab)).sockets).toBe(1);
    expect((await record(page)).liveTracks).toBe(0);
    await tab.close();
  });

  test('D4: streaming adds little main-thread script time', async ({
    page,
    baseURL
  }) => {
    await openLab(page, `${baseURL}/lab`);
    const cdp = await page.context().newCDPSession(page.page);
    await cdp.send('Performance.enable');
    const scriptSeconds = async (): Promise<number> => {
      const { metrics } = await cdp.send('Performance.getMetrics');
      return metrics.find(m => m.name === 'ScriptDuration')!.value;
    };
    const window = async (): Promise<number> => {
      const start = await scriptSeconds();
      await page.waitForTimeout(3000);
      return (await scriptSeconds()) - start;
    };

    const idle = await window();
    const status = page.locator(STATUS);
    await status.click();
    await expect(status).toHaveAttribute('data-vc-state', 'streaming', {
      timeout: 15000
    });
    await reader.waitForBytes(BYTES_PER_SECOND / 2);
    const streaming = await window();

    // Encoding runs in the AudioWorklet; the main thread only forwards 50 frames/s.
    test.info().annotations.push({
      type: 'main-thread script seconds per 3 s',
      description: `idle ${idle.toFixed(3)}, streaming ${streaming.toFixed(3)}`
    });
    expect(streaming - idle).toBeLessThan(0.15); // under 5% of the 3 s window
  });
});
