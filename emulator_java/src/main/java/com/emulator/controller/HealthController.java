package com.emulator.controller;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
public class HealthController {

    @Value("${emulator.version:1.0.0}")
    private String version;

    private final long startupTime = System.currentTimeMillis();

    @GetMapping("/health")
    public Map<String, Object> health() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("status", "healthy");
        result.put("service", "emulator");
        result.put("version", version);
        result.put("uptime_sec", Math.round((System.currentTimeMillis() - startupTime) / 100.0) / 10.0);
        return result;
    }
}
