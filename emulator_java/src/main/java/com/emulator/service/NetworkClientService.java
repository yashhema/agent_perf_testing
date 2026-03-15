package com.emulator.service;

import com.emulator.model.request.NetworkClientRequest;
import com.emulator.model.response.OperationResult;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Random;

@Service
public class NetworkClientService {

    private final ConfigService configService;
    private final HttpClient httpClient;

    public NetworkClientService(ConfigService configService) {
        this.configService = configService;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .build();
    }

    public OperationResult execute(NetworkClientRequest req) {
        long start = System.currentTimeMillis();
        String host = configService.getPartnerFqdn();
        int port = configService.getPartnerPort();
        long bytesSent = 0;
        long bytesReceived = 0;
        String errorMessage = null;

        try {
            // Build request payload of req_size_kb
            byte[] payload = new byte[req.getReqSizeKb() * 1024];
            new Random().nextBytes(payload);

            // Encode as base64 for JSON transport
            String payloadB64 = java.util.Base64.getEncoder().encodeToString(payload);

            String jsonBody = String.format(
                    "{\"payload\":\"%s\",\"resp_size_kb\":%d}",
                    payloadB64, req.getRespSizeKb()
            );

            URI uri = URI.create(String.format("http://%s:%d/api/v1/operations/networkserver", host, port));
            HttpRequest httpReq = HttpRequest.newBuilder()
                    .uri(uri)
                    .header("Content-Type", "application/json")
                    .timeout(Duration.ofSeconds(30))
                    .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
                    .build();

            bytesSent = jsonBody.length();
            HttpResponse<byte[]> resp = httpClient.send(httpReq, HttpResponse.BodyHandlers.ofByteArray());
            bytesReceived = resp.body().length;

            if (resp.statusCode() != 200) {
                errorMessage = "Partner returned HTTP " + resp.statusCode();
            }
        } catch (Exception e) {
            errorMessage = e.getClass().getSimpleName() + ": " + e.getMessage();
        }

        long elapsed = System.currentTimeMillis() - start;
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("partner_host", host);
        details.put("partner_port", port);
        details.put("req_size_kb", req.getReqSizeKb());
        details.put("resp_size_kb", req.getRespSizeKb());
        details.put("bytes_sent", bytesSent);
        details.put("bytes_received", bytesReceived);
        if (errorMessage != null) {
            details.put("error", errorMessage);
        }

        return new OperationResult("NET_CLIENT", errorMessage != null ? "error" : "completed", elapsed, details);
    }
}
