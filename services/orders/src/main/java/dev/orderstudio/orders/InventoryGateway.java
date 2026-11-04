package dev.orderstudio.orders;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.orderstudio.common.Api.StockRequest;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;

@FunctionalInterface
public interface InventoryGateway {
  record Reply(int status, String body) {}

  Reply put(String orderId, boolean release, StockRequest request, String requestId)
      throws Exception;

  static InventoryGateway http(String url, ObjectMapper mapper) {
    var client = HttpClient.newBuilder().connectTimeout(Duration.ofMillis(500)).build();
    return (id, release, request, rid) -> {
      var builder =
          HttpRequest.newBuilder(
                  URI.create(url + "/internal/v1/reservations/" + id + (release ? "/release" : "")))
              .timeout(Duration.ofSeconds(2))
              .header("Content-Type", "application/json");
      if (rid != null && !rid.isEmpty()) builder.header("X-Request-ID", rid);
      var response =
          client.send(
              builder
                  .PUT(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(request)))
                  .build(),
              HttpResponse.BodyHandlers.ofString());
      return new Reply(response.statusCode(), response.body());
    };
  }
}
