package com.emulator.controller;

import com.emulator.model.request.ConfigRequest;
import com.emulator.model.request.PoolRequest;
import com.emulator.model.response.PoolResponse;
import com.emulator.service.ConfigService;
import com.emulator.service.MemoryPoolService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/v1/config")
public class ConfigController {

    private final ConfigService configService;
    private final MemoryPoolService memoryPoolService;

    public ConfigController(ConfigService configService, MemoryPoolService memoryPoolService) {
        this.configService = configService;
        this.memoryPoolService = memoryPoolService;
    }

    @PostMapping
    public Map<String, Object> setConfig(@RequestBody ConfigRequest request) {
        return configService.setConfig(request);
    }

    @GetMapping
    public Map<String, Object> getConfig() {
        return configService.getConfigMap();
    }

    @PostMapping("/pool")
    public ResponseEntity<?> allocatePool(@RequestBody PoolRequest request) {
        if (request.getHeapPercent() != null) {
            double pct = request.getHeapPercent();
            if (pct <= 0 || pct > 0.8) {
                return ResponseEntity.badRequest().body(Map.of("detail",
                        "heap_percent must be between 0 (exclusive) and 0.8 (inclusive)"));
            }
            return ResponseEntity.ok(memoryPoolService.allocateByHeapPercent(pct));
        }
        if (request.getSizeGb() == null || request.getSizeGb() <= 0 || request.getSizeGb() > 64) {
            return ResponseEntity.badRequest().body(Map.of("detail",
                    "Provide heap_percent (0-0.8) or size_gb (0-64)"));
        }
        return ResponseEntity.ok(memoryPoolService.allocate(request.getSizeGb()));
    }

    @GetMapping("/pool")
    public PoolResponse getPoolStatus() {
        return memoryPoolService.getStatus();
    }

    @DeleteMapping("/pool")
    public PoolResponse destroyPool() {
        return memoryPoolService.destroy();
    }
}
