package com.emulator.service;

import com.emulator.model.request.NetRequest;
import com.emulator.model.response.OperationResult;
import org.springframework.stereotype.Service;

import java.io.*;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.util.*;

@Service
public class NetworkOperationService {

    private final ConfigService configService;

    public NetworkOperationService(ConfigService configService) {
        this.configService = configService;
    }

    public OperationResult execute(NetRequest req) {
        long start = System.currentTimeMillis();
        String host = req.getTargetHost() != null ? req.getTargetHost() : configService.getPartnerFqdn();
        Integer port = req.getTargetPort() != null ? req.getTargetPort() : configService.getPartnerPort();
        long bytesSent = 0, bytesReceived = 0;
        boolean connected = false;
        String errorMessage = null;

        if (host == null) {
            Map<String, Object> details = new LinkedHashMap<>();
            details.put("error", "No target host specified and no partner configured");
            return new OperationResult("NET", "error", 0, details);
        }

        try {
            Socket socket = new Socket(host, port);
            socket.setSoTimeout(1000);
            connected = true;

            byte[] packet = new byte[req.getPacketSizeBytes()];
            new Random().nextBytes(packet);
            long deadline = System.nanoTime() + (long) req.getDurationMs() * 1_000_000L;

            OutputStream out = socket.getOutputStream();
            InputStream in = socket.getInputStream();

            while (System.nanoTime() < deadline) {
                String mode = req.getMode();
                if ("send".equals(mode) || "both".equals(mode)) {
                    try {
                        out.write(packet);
                        out.flush();
                        bytesSent += packet.length;
                    } catch (Exception ignored) { break; }
                }
                if ("receive".equals(mode) || "both".equals(mode)) {
                    try {
                        byte[] buf = new byte[req.getPacketSizeBytes()];
                        int n = in.read(buf);
                        if (n > 0) bytesReceived += n;
                    } catch (SocketTimeoutException ignored) {
                    } catch (Exception ignored) { break; }
                }
            }

            socket.close();
        } catch (Exception e) {
            errorMessage = e.getMessage();
        }

        long elapsed = System.currentTimeMillis() - start;
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("requested_duration_ms", req.getDurationMs());
        details.put("target_host", host);
        details.put("target_port", port);
        details.put("mode", req.getMode());
        details.put("bytes_sent", bytesSent);
        details.put("bytes_received", bytesReceived);
        details.put("connection_established", connected);
        details.put("error_message", errorMessage);

        return new OperationResult("NET", "completed", elapsed, details);
    }
}
