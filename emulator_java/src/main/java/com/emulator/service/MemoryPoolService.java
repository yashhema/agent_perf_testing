package com.emulator.service;

import com.emulator.model.response.PoolResponse;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import java.util.concurrent.locks.ReentrantLock;

@Service
public class MemoryPoolService {

    private volatile byte[][] chunks;
    private volatile int chunkSize;
    private volatile long poolSizeBytes;
    private final ReentrantLock lock = new ReentrantLock();
    private static final int PAGE_SIZE = 4096;
    // Max per-chunk: 1.5 GB (well under Integer.MAX_VALUE, leaves room for JVM overhead)
    private static final int MAX_CHUNK_BYTES = (int) (1.5 * 1024 * 1024 * 1024);

    /**
     * Allocate pool as a percentage of the JVM max heap.
     * The emulator knows its own heap — this keeps sizing self-contained.
     */
    public PoolResponse allocateByHeapPercent(double heapPercent) {
        long maxHeap = Runtime.getRuntime().maxMemory();
        long sizeBytes = (long) (maxHeap * heapPercent);
        double sizeGb = sizeBytes / (1024.0 * 1024.0 * 1024.0);
        return allocate(sizeGb);
    }

    public PoolResponse allocate(double sizeGb) {
        lock.lock();
        try {
            if (chunks != null) {
                chunks = null;
                System.gc();
            }
            long sizeBytes = (long) (sizeGb * 1024L * 1024L * 1024L);

            // Split into chunks of MAX_CHUNK_BYTES
            int numChunks = (int) ((sizeBytes + MAX_CHUNK_BYTES - 1) / MAX_CHUNK_BYTES);
            if (numChunks < 1) numChunks = 1;
            int perChunk = (int) (sizeBytes / numChunks);

            chunks = new byte[numChunks][];
            long totalAllocated = 0;
            for (int c = 0; c < numChunks; c++) {
                // Last chunk gets the remainder
                int thisChunk = (c == numChunks - 1)
                        ? (int) (sizeBytes - totalAllocated)
                        : perChunk;
                chunks[c] = new byte[thisChunk];
                // Touch all pages to force physical allocation
                for (int i = 0; i < thisChunk; i += PAGE_SIZE) {
                    chunks[c][i] = (byte) (i & 0xFF);
                }
                totalAllocated += thisChunk;
            }
            chunkSize = perChunk;
            poolSizeBytes = totalAllocated;

            return new PoolResponse(true, poolSizeBytes);
        } finally {
            lock.unlock();
        }
    }

    public PoolResponse getStatus() {
        return new PoolResponse(chunks != null, chunks != null ? poolSizeBytes : 0);
    }

    public PoolResponse destroy() {
        lock.lock();
        try {
            chunks = null;
            chunkSize = 0;
            poolSizeBytes = 0;
            System.gc();
            return new PoolResponse(false, 0);
        } finally {
            lock.unlock();
        }
    }

    public boolean isAllocated() {
        return chunks != null;
    }

    /**
     * Touch a region of the pool. Returns number of pages touched.
     * Maps virtual flat address to chunk[index][offset].
     */
    public int touchPool(double touchMb, String pattern) {
        byte[][] ch = chunks;
        if (ch == null || ch.length == 0 || touchMb <= 0) return 0;

        long totalBytes = poolSizeBytes;
        long bytesToTouch = (long) (touchMb * 1024 * 1024);
        bytesToTouch = Math.min(bytesToTouch, totalBytes);
        int pages = (int) (bytesToTouch / PAGE_SIZE);
        if (pages == 0) pages = 1;

        if ("sequential".equals(pattern)) {
            Random rng = ThreadLocal.withInitial(Random::new).get();
            long startPos = (long) (rng.nextDouble() * Math.max(1, totalBytes - bytesToTouch));
            for (int i = 0; i < pages; i++) {
                long virtualIdx = startPos + ((long) i * PAGE_SIZE);
                if (virtualIdx >= totalBytes) break;
                int ci = (int) (virtualIdx / ch[0].length);
                int offset = (int) (virtualIdx % ch[0].length);
                if (ci < ch.length && offset < ch[ci].length) {
                    ch[ci][offset] = (byte) (ch[ci][offset] + 1);
                }
            }
        } else {
            // Random access across all chunks
            Random rng = ThreadLocal.withInitial(Random::new).get();
            for (int i = 0; i < pages; i++) {
                long virtualIdx = (long) (rng.nextDouble() * totalBytes);
                int ci = (int) (virtualIdx / ch[0].length);
                int offset = (int) (virtualIdx % ch[0].length);
                if (ci < ch.length && offset < ch[ci].length) {
                    ch[ci][offset] = (byte) (ch[ci][offset] + 1);
                }
            }
        }
        return pages;
    }
}
