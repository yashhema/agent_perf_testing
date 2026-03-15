package com.emulator.controller;

import com.emulator.service.StatsCollectorService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.io.FileNotFoundException;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/stats")
public class StatsController {

    private final StatsCollectorService statsCollector;

    public StatsController(StatsCollectorService statsCollector) {
        this.statsCollector = statsCollector;
    }

    @GetMapping("/system")
    public Map<String, Object> systemStats() {
        return statsCollector.getSystemStats();
    }

    @GetMapping("/recent")
    public Map<String, Object> recentStats(@RequestParam(defaultValue = "100") int count) {
        count = Math.max(1, Math.min(1000, count));
        return statsCollector.getRecentStats(count);
    }

    @GetMapping("/all")
    public ResponseEntity<?> allStats(@RequestParam("test_run_id") String testRunId,
                                       @RequestParam(value = "scenario_id", required = false) String scenarioId) {
        try {
            return ResponseEntity.ok(statsCollector.getAllStats(testRunId));
        } catch (IllegalStateException e) {
            return ResponseEntity.badRequest().body(Map.of("detail", e.getMessage()));
        } catch (FileNotFoundException e) {
            return ResponseEntity.status(404).body(Map.of("detail", e.getMessage()));
        } catch (Exception e) {
            return ResponseEntity.status(500).body(Map.of("detail", "Error reading stats: " + e.getMessage()));
        }
    }

    @GetMapping("/iterations")
    public Map<String, Object> iterationTiming() {
        return statsCollector.getIterationTiming();
    }

    @PostMapping("/iterations/clear")
    public Map<String, Object> clearIterations() {
        return statsCollector.clearIterationTimes();
    }
}
