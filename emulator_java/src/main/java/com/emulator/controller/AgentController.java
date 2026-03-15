package com.emulator.controller;

import com.emulator.model.request.AgentInstallRequest;
import com.emulator.model.request.AgentServiceRequest;
import com.emulator.model.request.AgentUninstallRequest;
import com.emulator.service.AgentService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.Set;

@RestController
@RequestMapping("/api/v1/agent")
public class AgentController {

    private static final Set<String> KNOWN_AGENTS = Set.of("crowdstrike", "sentinelone", "carbonblack");

    private final AgentService agentService;

    public AgentController(AgentService agentService) {
        this.agentService = agentService;
    }

    @GetMapping("/{agentType}")
    public ResponseEntity<?> getAgentInfo(@PathVariable String agentType) {
        if (!KNOWN_AGENTS.contains(agentType.toLowerCase())) {
            return ResponseEntity.badRequest().body(Map.of("detail", "Unknown agent type: " + agentType));
        }
        return ResponseEntity.ok(agentService.getAgentInfo(agentType));
    }

    @PostMapping("/install")
    public Map<String, Object> installAgent(@RequestBody AgentInstallRequest request) {
        return agentService.installAgent(request.getAgentType(), request.getInstallerPath(), request.getInstallOptions());
    }

    @PostMapping("/uninstall")
    public Map<String, Object> uninstallAgent(@RequestBody AgentUninstallRequest request) {
        return agentService.uninstallAgent(request.getAgentType(), request.isForce());
    }

    @PostMapping("/service")
    public ResponseEntity<?> serviceControl(@RequestBody AgentServiceRequest request) {
        String action = request.getAction();
        if (action == null || !Set.of("start", "stop", "restart").contains(action)) {
            return ResponseEntity.badRequest().body(Map.of("detail", "Invalid action. Must be start, stop, or restart."));
        }
        return ResponseEntity.ok(agentService.controlService(request.getAgentType(), action));
    }
}
