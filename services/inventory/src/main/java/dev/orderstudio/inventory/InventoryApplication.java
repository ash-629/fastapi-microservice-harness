package dev.orderstudio.inventory;

import java.util.Arrays;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.builder.SpringApplicationBuilder;

@SpringBootApplication(scanBasePackages = {"dev.orderstudio.inventory", "dev.orderstudio.common"})
public class InventoryApplication {
  public static void main(String[] args) {
    if (Arrays.asList(args).contains("--seed")) {
      try (var context =
          new SpringApplicationBuilder(InventoryApplication.class)
              .web(WebApplicationType.NONE)
              .run(args)) {
        context.getBean(InventoryService.class).ready();
        System.out.println("Missing products initialized");
      }
      return;
    }
    SpringApplication.run(InventoryApplication.class, args);
  }
}
