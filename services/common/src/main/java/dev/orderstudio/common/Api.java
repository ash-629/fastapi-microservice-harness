package dev.orderstudio.common;

import com.fasterxml.jackson.annotation.JsonPropertyOrder;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

public final class Api {
  private Api() {}

  @Schema(name = "Request", additionalProperties = Schema.AdditionalPropertiesValue.FALSE)
  @JsonPropertyOrder({"product_id", "quantity"})
  public record StockRequest(
      @NotBlank @Size(max = 80) String product_id, @NotNull @Min(1) @Max(99) Integer quantity) {
    public StockRequest {
      if (product_id != null) product_id = product_id.strip();
    }
  }

  @Schema(requiredProperties = {"code", "message", "details"})
  public record ErrorDetail(String code, String message, Map<String, Object> details) {}

  @Schema(
      name = "Error",
      requiredProperties = {"error", "request_id"})
  public record ErrorEnvelope(ErrorDetail error, String request_id) {}

  public static final class Failure extends RuntimeException {
    public final int status;
    public final Map<String, Object> details;

    public Failure(int status, String code) {
      this(status, code, Map.of());
    }

    public Failure(int status, String code, Map<String, Object> details) {
      super(code);
      this.status = status;
      this.details = details;
    }
  }

  public static String uuid(String value) {
    if (value == null
        || !value.matches("(?i)[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"))
      throw new Failure(422, "VALIDATION_ERROR");
    return UUID.fromString(value).toString();
  }

  public static String digest(StockRequest request, ObjectMapper mapper) {
    try {
      return HexFormat.of()
          .formatHex(
              MessageDigest.getInstance("SHA-256")
                  .digest(mapper.writeValueAsString(request).getBytes(StandardCharsets.UTF_8)));
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
  }

  public static ErrorEnvelope error(String code, String rid, Map<String, Object> details) {
    return new ErrorEnvelope(new ErrorDetail(code, code, details), rid);
  }
}
