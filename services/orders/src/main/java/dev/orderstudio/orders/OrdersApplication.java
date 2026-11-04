package dev.orderstudio.orders;

import java.util.Arrays;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.scheduling.annotation.EnableScheduling;

@EnableScheduling
@SpringBootApplication(scanBasePackages = {"dev.orderstudio.orders", "dev.orderstudio.common"})
public class OrdersApplication {
  public static void main(String[] args) {
    if (Arrays.asList(args).contains("--reconcile")) {
      try (var context =
          new SpringApplicationBuilder(OrdersApplication.class)
              .web(WebApplicationType.NONE)
              .run(
                  java.util.stream.Stream.concat(
                          Arrays.stream(args),
                          java.util.stream.Stream.of("--studio.recovery=false"))
                      .toArray(String[]::new))) {
        String id =
            Arrays.stream(args)
                .filter(a -> a.startsWith("--order-id="))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("--order-id required"))
                .substring("--order-id=".length());
        System.out.println(
            "Reconciled: "
                + context
                    .getBean(OrderService.class)
                    .reconcile(dev.orderstudio.common.Api.uuid(id)));
      }
      return;
    }
    SpringApplication.run(OrdersApplication.class, args);
  }
}
