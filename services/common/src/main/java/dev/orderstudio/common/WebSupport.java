package dev.orderstudio.common;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.cfg.*;
import com.fasterxml.jackson.databind.type.LogicalType;
import io.swagger.v3.oas.annotations.Hidden;
import io.swagger.v3.oas.models.*;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.servers.Server;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import jakarta.validation.ConstraintViolationException;
import java.io.IOException;
import java.util.*;
import org.slf4j.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.*;
import org.springframework.http.*;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.BindException;
import org.springframework.web.HttpMediaTypeNotAcceptableException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.method.annotation.*;
import org.springframework.web.servlet.resource.NoResourceFoundException;

@Configuration
public class WebSupport {
  @Bean
  Jackson2ObjectMapperBuilderCustomizer strictJson() {
    return b ->
        b.featuresToEnable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .featuresToDisable(DeserializationFeature.ACCEPT_FLOAT_AS_INT)
            .postConfigurer(
                m -> {
                  for (var shape :
                      List.of(
                          CoercionInputShape.Integer,
                          CoercionInputShape.Float,
                          CoercionInputShape.Boolean))
                    m.coercionConfigFor(LogicalType.Textual)
                        .setCoercion(shape, CoercionAction.Fail);
                  for (var shape :
                      List.of(
                          CoercionInputShape.String,
                          CoercionInputShape.Float,
                          CoercionInputShape.Boolean))
                    m.coercionConfigFor(LogicalType.Integer)
                        .setCoercion(shape, CoercionAction.Fail);
                });
  }

  @Bean
  OpenAPI openAPI(
      @Value("${spring.application.name}") String name,
      @Value("${studio.version}") String version) {
    return new OpenAPI()
        .info(new Info().title(name).version(version))
        .servers(List.of(new Server().url("/")));
  }

  @Bean
  Trace trace(ObjectMapper mapper, @Value("${spring.application.name}") String name) {
    return new Trace(mapper, name);
  }

  static final class Trace extends OncePerRequestFilter {
    private static final Logger log = LoggerFactory.getLogger(Trace.class);
    private final ObjectMapper mapper;
    private final String name;

    Trace(ObjectMapper mapper, String name) {
      this.mapper = mapper;
      this.name = name;
    }

    @Override
    protected void doFilterInternal(
        HttpServletRequest req, HttpServletResponse res, FilterChain chain)
        throws ServletException, IOException {
      String rid;
      try {
        rid = Api.uuid(req.getHeader("X-Request-ID"));
      } catch (Api.Failure e) {
        rid = UUID.randomUUID().toString();
      }
      req.setAttribute("request_id", rid);
      res.setHeader("X-Request-ID", rid);
      long start = System.nanoTime();
      try {
        chain.doFilter(req, res);
      } finally {
        log.info(
            mapper.writeValueAsString(
                Map.of(
                    "service",
                    name,
                    "request_id",
                    rid,
                    "method",
                    req.getMethod(),
                    "path",
                    req.getRequestURI(),
                    "status_code",
                    res.getStatus(),
                    "duration_ms",
                    (System.nanoTime() - start) / 1_000_000.0)));
      }
    }
  }

  @RestControllerAdvice
  public static class Errors {
    @ExceptionHandler(Api.Failure.class)
    ResponseEntity<Api.ErrorEnvelope> failure(Api.Failure e, HttpServletRequest r) {
      return response(e.status, e.getMessage(), e.details, r);
    }

    @ExceptionHandler({
      BindException.class,
      HttpMessageNotReadableException.class,
      MethodArgumentTypeMismatchException.class,
      MissingRequestHeaderException.class,
      ConstraintViolationException.class,
      org.springframework.web.method.annotation.HandlerMethodValidationException.class
    })
    ResponseEntity<Api.ErrorEnvelope> validation(Exception e, HttpServletRequest r) {
      return response(422, "VALIDATION_ERROR", Map.of(), r);
    }

    @ExceptionHandler(Database.StorageException.class)
    ResponseEntity<Api.ErrorEnvelope> storage(Exception e, HttpServletRequest r) {
      return response(503, "STORAGE_UNAVAILABLE", Map.of(), r);
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    ResponseEntity<Api.ErrorEnvelope> method(
        HttpRequestMethodNotSupportedException e, HttpServletRequest r) {
      return ResponseEntity.status(405)
          .headers(e.getHeaders())
          .body(
              Api.error(
                  "METHOD_NOT_ALLOWED", String.valueOf(r.getAttribute("request_id")), Map.of()));
    }

    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    ResponseEntity<Api.ErrorEnvelope> mediaType(
        HttpMediaTypeNotSupportedException e, HttpServletRequest r) {
      return ResponseEntity.status(415)
          .headers(e.getHeaders())
          .body(
              Api.error(
                  "UNSUPPORTED_MEDIA_TYPE",
                  String.valueOf(r.getAttribute("request_id")),
                  Map.of()));
    }

    @ExceptionHandler(HttpMediaTypeNotAcceptableException.class)
    ResponseEntity<Api.ErrorEnvelope> accept(
        HttpMediaTypeNotAcceptableException e, HttpServletRequest r) {
      return ResponseEntity.status(406)
          .contentType(MediaType.APPLICATION_JSON)
          .body(
              Api.error("NOT_ACCEPTABLE", String.valueOf(r.getAttribute("request_id")), Map.of()));
    }

    @ExceptionHandler(NoResourceFoundException.class)
    ResponseEntity<Api.ErrorEnvelope> missing(Exception e, HttpServletRequest r) {
      return response(404, "NOT_FOUND", Map.of(), r);
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<Api.ErrorEnvelope> internal(Exception e, HttpServletRequest r) {
      LoggerFactory.getLogger(Errors.class).error("Unhandled request", e);
      return response(500, "INTERNAL_ERROR", Map.of(), r);
    }

    private ResponseEntity<Api.ErrorEnvelope> response(
        int status, String code, Map<String, Object> details, HttpServletRequest r) {
      return ResponseEntity.status(status)
          .body(Api.error(code, String.valueOf(r.getAttribute("request_id")), details));
    }
  }

  @Hidden
  @RestController
  public static class Docs {
    @GetMapping("/docs")
    ResponseEntity<Void> docs() {
      return ResponseEntity.status(302).header("Location", "/swagger-ui/index.html").build();
    }
  }
}
