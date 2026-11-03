import { createApp } from "vue";
import App from "./App.vue";
import "./style.css";
async function start() {
  if (import.meta.env.VITE_MOCK === "1") {
    const { setupWorker } = await import("msw/browser");
    const { handlers } = await import("./mocks/handlers");
    await setupWorker(...handlers).start({ onUnhandledRequest: "bypass" });
  }
  createApp(App).mount("#app");
}
void start();
