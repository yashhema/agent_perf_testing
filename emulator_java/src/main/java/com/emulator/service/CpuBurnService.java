package com.emulator.service;

import org.springframework.stereotype.Service;

@Service
public class CpuBurnService {

    /**
     * Burns CPU for the specified duration with given intensity.
     * Uses tight arithmetic loops that actually saturate a core.
     * With intensity < 1.0, alternates between burn and sleep.
     *
     * @return actual wall-time duration in ms
     */
    public long burn(int durationMs, double intensity) {
        long startNanos = System.nanoTime();
        long totalNanos = (long) durationMs * 1_000_000L;

        if (intensity >= 1.0) {
            // Full burn — tight loop until deadline
            burnUntil(startNanos + totalNanos);
        } else if (intensity <= 0.0) {
            // No burn — just sleep
            try { Thread.sleep(durationMs); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
        } else {
            // Alternating burn/sleep in small intervals
            long intervalNanos = 10_000_000L; // 10ms intervals
            long burnPerInterval = (long) (intervalNanos * intensity);
            long sleepPerInterval = intervalNanos - burnPerInterval;
            long deadline = startNanos + totalNanos;

            while (System.nanoTime() < deadline) {
                long intervalStart = System.nanoTime();
                // Burn phase
                burnUntil(intervalStart + burnPerInterval);
                // Sleep phase
                if (sleepPerInterval > 1_000_000L) {
                    try { Thread.sleep(sleepPerInterval / 1_000_000L); }
                    catch (InterruptedException e) { Thread.currentThread().interrupt(); break; }
                }
            }
        }

        return (System.nanoTime() - startNanos) / 1_000_000L;
    }

    /**
     * Tight arithmetic loop that saturates a core until the deadline.
     * This is the key difference from Python — Java threads are real OS threads,
     * so multiple calls to this from different threads burn on separate cores.
     */
    private void burnUntil(long deadlineNanos) {
        double x = 1.0;
        while (System.nanoTime() < deadlineNanos) {
            // Mix of operations to prevent JIT from optimizing away
            x = Math.sin(x) + Math.sqrt(x + 1.0) + Math.cos(x);
            x = Math.sin(x) + Math.sqrt(x + 1.0) + Math.cos(x);
            x = Math.sin(x) + Math.sqrt(x + 1.0) + Math.cos(x);
            x = Math.sin(x) + Math.sqrt(x + 1.0) + Math.cos(x);
        }
        // Prevent dead-code elimination
        if (x == Double.NaN) System.out.print("");
    }
}
