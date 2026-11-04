package dev.orderstudio.common;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.*;

class WebSupportTest {
  private MockMvc mvc;

  @RestController
  static class ExampleController {
    @GetMapping(value = "/sample", produces = MediaType.APPLICATION_JSON_VALUE)
    String get() {
      return "ok";
    }

    @PostMapping(value = "/sample", consumes = MediaType.APPLICATION_JSON_VALUE)
    String post(@RequestBody Api.StockRequest request) {
      return request.product_id();
    }

    @GetMapping("/failure")
    void failure() {
      throw new IllegalStateException("private-exception-detail");
    }

    @GetMapping("/storage")
    void storage() {
      throw new Database.StorageException(new java.sql.SQLException("private-database-detail"));
    }
  }

  @BeforeEach
  void setup() {
    mvc =
        MockMvcBuilders.standaloneSetup(new ExampleController())
            .setControllerAdvice(new WebSupport.Errors())
            .build();
  }

  @Test
  void unsupportedMethodIsClientError() throws Exception {
    mvc.perform(put("/sample").requestAttr("request_id", "test-request"))
        .andExpect(status().isMethodNotAllowed())
        .andExpect(header().string("Allow", org.hamcrest.Matchers.containsString("GET")))
        .andExpect(jsonPath("$.error.code").value("METHOD_NOT_ALLOWED"))
        .andExpect(jsonPath("$.request_id").value("test-request"));
  }

  @Test
  void unsupportedBodyMediaTypeIsClientError() throws Exception {
    mvc.perform(
            post("/sample")
                .contentType(MediaType.TEXT_PLAIN)
                .content("body")
                .requestAttr("request_id", "test-request"))
        .andExpect(status().isUnsupportedMediaType())
        .andExpect(jsonPath("$.error.code").value("UNSUPPORTED_MEDIA_TYPE"));
  }

  @Test
  void unacceptableResponseTypeIsClientError() throws Exception {
    mvc.perform(
            get("/sample").accept(MediaType.TEXT_PLAIN).requestAttr("request_id", "test-request"))
        .andExpect(status().isNotAcceptable())
        .andExpect(jsonPath("$.error.code").value("NOT_ACCEPTABLE"));
  }

  @Test
  void storageFailureReturns503WithoutDetails() throws Exception {
    mvc.perform(get("/storage").requestAttr("request_id", "test-request"))
        .andExpect(status().isServiceUnavailable())
        .andExpect(jsonPath("$.error.code").value("STORAGE_UNAVAILABLE"))
        .andExpect(
            content()
                .string(
                    org.hamcrest.Matchers.not(
                        org.hamcrest.Matchers.containsString("private-database-detail"))));
  }

  @Test
  void internalFailureReturns500WithoutDetails() throws Exception {
    mvc.perform(get("/failure").requestAttr("request_id", "test-request"))
        .andExpect(status().isInternalServerError())
        .andExpect(jsonPath("$.error.code").value("INTERNAL_ERROR"))
        .andExpect(
            content()
                .string(
                    org.hamcrest.Matchers.not(
                        org.hamcrest.Matchers.containsString("private-exception-detail"))));
  }
}
