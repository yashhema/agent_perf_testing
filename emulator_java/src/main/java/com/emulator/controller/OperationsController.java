package com.emulator.controller;

import com.emulator.model.request.*;
import com.emulator.model.response.FileOperationResult;
import com.emulator.model.response.OperationResult;
import com.emulator.service.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
@RequestMapping("/api/v1/operations")
public class OperationsController {

    private final CpuBurnService cpuBurnService;
    private final MemoryPoolService memoryPoolService;
    private final DiskOperationService diskOperationService;
    private final NetworkOperationService networkOperationService;
    private final NetworkClientService networkClientService;
    private final FileOperationService fileOperationService;
    private final SuspiciousOperationService suspiciousOperationService;
    private final ConfigService configService;

    public OperationsController(CpuBurnService cpuBurnService,
                                MemoryPoolService memoryPoolService,
                                DiskOperationService diskOperationService,
                                NetworkOperationService networkOperationService,
                                NetworkClientService networkClientService,
                                FileOperationService fileOperationService,
                                SuspiciousOperationService suspiciousOperationService,
                                ConfigService configService) {
        this.cpuBurnService = cpuBurnService;
        this.memoryPoolService = memoryPoolService;
        this.diskOperationService = diskOperationService;
        this.networkOperationService = networkOperationService;
        this.networkClientService = networkClientService;
        this.fileOperationService = fileOperationService;
        this.suspiciousOperationService = suspiciousOperationService;
        this.configService = configService;
    }

    @PostMapping("/cpu")
    public OperationResult cpuOperation(@RequestBody CpuRequest request) {
        long start = System.currentTimeMillis();
        cpuBurnService.burn(request.getDurationMs(), request.getIntensity());
        long elapsed = System.currentTimeMillis() - start;

        Map<String, Object> details = new LinkedHashMap<>();
        details.put("requested_duration_ms", request.getDurationMs());
        details.put("intensity", request.getIntensity());

        return new OperationResult("CPU", "completed", elapsed, details);
    }

    @PostMapping("/mem")
    public OperationResult memOperation(@RequestBody MemRequest request) {
        long start = System.currentTimeMillis();
        int accessCount = 0;

        // Allocate memory
        int sizeBytes = request.getSizeMb() * 1024 * 1024;
        byte[] buffer = new byte[sizeBytes];

        // Touch all pages
        for (int i = 0; i < buffer.length; i += 4096) {
            buffer[i] = (byte) (i & 0xFF);
        }

        // Access pattern for duration
        long deadline = System.nanoTime() + (long) request.getDurationMs() * 1_000_000L;
        Random rng = new Random();

        while (System.nanoTime() < deadline) {
            if ("random".equals(request.getPattern())) {
                int idx = rng.nextInt(buffer.length);
                buffer[idx] = (byte) (buffer[idx] + 1);
            } else {
                for (int i = 0; i < buffer.length && System.nanoTime() < deadline; i += 4096) {
                    buffer[i] = (byte) (buffer[i] + 1);
                    accessCount++;
                }
            }
            accessCount++;
        }

        // Release
        buffer = null;
        long elapsed = System.currentTimeMillis() - start;

        Map<String, Object> details = new LinkedHashMap<>();
        details.put("requested_duration_ms", request.getDurationMs());
        details.put("size_mb", request.getSizeMb());
        details.put("pattern", request.getPattern());
        details.put("access_count", accessCount);

        return new OperationResult("MEM", "completed", elapsed, details);
    }

    @PostMapping("/disk")
    public OperationResult diskOperation(@RequestBody DiskRequest request) {
        return diskOperationService.execute(request);
    }

    @PostMapping("/net")
    public ResponseEntity<?> netOperation(@RequestBody NetRequest request) {
        String host = request.getTargetHost() != null ? request.getTargetHost() : configService.getPartnerFqdn();
        if (host == null) {
            return ResponseEntity.badRequest().body(Map.of("detail",
                    "No target host specified and no partner configured"));
        }
        return ResponseEntity.ok(networkOperationService.execute(request));
    }

    @PostMapping("/networkclient")
    public ResponseEntity<?> networkClientOperation(@RequestBody NetworkClientRequest request) {
        String host = configService.getPartnerFqdn();
        if (host == null) {
            return ResponseEntity.badRequest().body(Map.of("detail",
                    "No partner configured. POST /api/v1/config with partner first."));
        }
        return ResponseEntity.ok(networkClientService.execute(request));
    }

    @PostMapping("/networkserver")
    public ResponseEntity<?> networkServerOperation(@RequestBody NetworkServerRequest request) {
        long start = System.currentTimeMillis();
        // Build response payload of requested size
        byte[] respPayload = new byte[request.getRespSizeKb() * 1024];
        new java.util.Random().nextBytes(respPayload);
        String respB64 = java.util.Base64.getEncoder().encodeToString(respPayload);

        long elapsed = System.currentTimeMillis() - start;
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("received_bytes", request.getPayload() != null ? request.getPayload().length : 0);
        details.put("resp_size_kb", request.getRespSizeKb());
        details.put("response_payload", respB64);

        return ResponseEntity.ok(new OperationResult("NET_SERVER", "completed", elapsed, details));
    }

    @PostMapping("/file")
    public ResponseEntity<?> fileOperation(@RequestBody FileOperationRequest request) {
        List<String> folders = configService.getOutputFolders();
        if (folders == null || folders.isEmpty()) {
            return ResponseEntity.badRequest().body(Map.of("detail",
                    "No output folders configured. POST /api/v1/config first."));
        }
        return ResponseEntity.ok(fileOperationService.execute(request));
    }

    @PostMapping("/work")
    public ResponseEntity<?> workOperation(@RequestBody WorkRequest request) {
        if (!memoryPoolService.isAllocated()) {
            return ResponseEntity.badRequest().body(Map.of("detail",
                    "Memory pool not initialised. POST /api/v1/config/pool first."));
        }

        long start = System.currentTimeMillis();

        // CPU burn — this is the critical path. Real OS thread, no GIL.
        cpuBurnService.burn(request.getCpuMs(), request.getIntensity());

        // Touch memory pool
        int pagesTouched = memoryPoolService.touchPool(request.getTouchMb(), request.getTouchPattern());

        long elapsed = System.currentTimeMillis() - start;
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("cpu_ms_actual", request.getCpuMs());
        details.put("pages_touched", pagesTouched);

        return ResponseEntity.ok(new OperationResult("WORK", "completed", elapsed, details));
    }

    @PostMapping("/suspicious")
    public OperationResult suspiciousOperation(@RequestBody SuspiciousRequest request) {
        return suspiciousOperationService.execute(request);
    }
}
