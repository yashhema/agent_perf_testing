package com.emulator.controller;

import com.emulator.model.request.StartTestRequest;
import com.emulator.model.request.StopTestRequest;
import com.emulator.model.response.TestStatusResponse;
import com.emulator.service.TestManagerService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/tests")
public class TestsController {

    private final TestManagerService testManager;

    public TestsController(TestManagerService testManager) {
        this.testManager = testManager;
    }

    @PostMapping("/start")
    public TestStatusResponse startTest(@RequestBody StartTestRequest request) {
        return testManager.startTest(request);
    }

    // Legacy alias — POST /api/v1/tests/ (with or without trailing slash)
    @PostMapping({"", "/"})
    public TestStatusResponse startTestLegacy(@RequestBody StartTestRequest request) {
        return testManager.startTest(request);
    }

    @GetMapping({"", "/"})
    public List<TestStatusResponse> listTests() {
        return testManager.listTests();
    }

    @GetMapping("/{testId}")
    public ResponseEntity<?> getTest(@PathVariable String testId) {
        TestStatusResponse resp = testManager.getTest(testId);
        if (resp == null) {
            return ResponseEntity.status(404).body(Map.of("detail", "Test not found"));
        }
        return ResponseEntity.ok(resp);
    }

    @PostMapping("/{testId}/stop")
    public ResponseEntity<?> stopTest(@PathVariable String testId,
                                       @RequestBody(required = false) StopTestRequest request) {
        boolean force = request != null && request.isForce();
        Map<String, Object> result = testManager.stopTest(testId, force);
        if (result == null) {
            return ResponseEntity.status(404).body(Map.of("detail", "Test not found"));
        }
        return ResponseEntity.ok(result);
    }
}
