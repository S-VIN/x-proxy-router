/** The current time, updated every second, for relative times and countdowns. */
class Clock {
  now = $state(Date.now());

  constructor(intervalMs: number) {
    setInterval(() => (this.now = Date.now()), intervalMs);
  }
}

export const clock = new Clock(1000);
