<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import * as api from "./api/client";
import type { Product } from "./api/generated/inventory/types.gen";
const items = ref<Product[]>([]),
  rows = ref<api.Order[]>([]),
  selected = ref(""),
  quantity = ref(1);
const status = ref<api.Order["status"] | "">(""),
  offset = ref(0),
  total = ref(0);
const busy = ref(false),
  loading = ref(true),
  error = ref(""),
  notice = ref(""),
  active = ref<api.Order | null>(null);
const labels: Record<api.Order["status"], string> = {
  CONFIRMED: "已确认",
  REJECTED: "已拒绝",
  PENDING_INVENTORY: "确认中",
};
interface Pending {
  body: string;
  key: string;
  orderId?: string;
}
let memory: Pending | null = null,
  loadVersion = 0,
  detailVersion = 0,
  disposed = false;
let timer: ReturnType<typeof setTimeout> | undefined;
const message = (e: unknown) =>
  e instanceof Error ? e.message : "请求失败，请稍后重试";
function readPending(): Pending | null {
  try {
    const p = JSON.parse(sessionStorage.getItem("pending-order") || "null");
    if (
      p &&
      typeof p.body === "string" &&
      typeof p.key === "string" &&
      /^[0-9a-f-]{36}$/i.test(p.key)
    )
      return p;
  } catch {
    /* 存储不可用时保留内存幂等标识。 */
  }
  return memory;
}
function savePending(p: Pending) {
  memory = p;
  try {
    sessionStorage.setItem("pending-order", JSON.stringify(p));
  } catch {
    /* 同一页面内仍按相同键重试。 */
  }
}
function clearPending(id: string) {
  const p = readPending();
  if (p?.orderId !== id) return;
  memory = null;
  try {
    sessionStorage.removeItem("pending-order");
  } catch {
    /* 不影响业务完成。 */
  }
}
function cancelPoll() {
  detailVersion++;
  clearTimeout(timer);
}
function closeDetail() {
  cancelPoll();
  active.value = null;
}
function describe(o: api.Order) {
  notice.value =
    o.status === "CONFIRMED"
      ? "订单已确认"
      : o.status === "REJECTED"
        ? "订单已拒绝，请查看原因"
        : "订单正在确认库存";
}
async function load() {
  const version = ++loadVersion;
  loading.value = true;
  try {
    const [p, o] = await Promise.all([
      api.products(),
      api.orders(status.value, offset.value),
    ]);
    if (disposed || version !== loadVersion) return;
    items.value = p.items;
    rows.value = o.items;
    total.value = o.total;
    if (!selected.value && p.items.length)
      selected.value = p.items[0].product_id;
  } catch (e) {
    if (!disposed && version === loadVersion) error.value = message(e);
  } finally {
    if (!disposed && version === loadVersion) loading.value = false;
  }
}
function poll(id: string, start: number, version: number) {
  timer = setTimeout(async () => {
    try {
      const o = await api.detail(id);
      if (disposed || version !== detailVersion) return;
      active.value = o;
      describe(o);
      if (o.status === "PENDING_INVENTORY" && Date.now() - start < 30000)
        poll(id, start, version);
      else {
        if (o.status !== "PENDING_INVENTORY") clearPending(id);
        await load();
      }
    } catch (e) {
      if (!disposed && version === detailVersion) error.value = message(e);
    }
  }, 1500);
}
function showOrder(o: api.Order) {
  cancelPoll();
  active.value = o;
  if (o.status === "PENDING_INVENTORY")
    poll(o.order_id, Date.now(), detailVersion);
}
async function refreshDetail() {
  const id = active.value?.order_id,
    version = detailVersion;
  if (!id) return;
  try {
    const o = await api.detail(id);
    if (disposed || version !== detailVersion) return;
    active.value = o;
    describe(o);
    if (o.status !== "PENDING_INVENTORY") {
      cancelPoll();
      clearPending(id);
      await load();
    }
  } catch (e) {
    if (!disposed && version === detailVersion) error.value = message(e);
  }
}
async function submit() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  cancelPoll();
  let pending: Pending | null = null;
  try {
    const body = JSON.stringify({
      product_id: selected.value,
      quantity: quantity.value,
    });
    pending = readPending();
    if (!pending || pending.body !== body)
      pending = { body, key: crypto.randomUUID() };
    savePending(pending);
    const o = await api.create(selected.value, quantity.value, pending.key);
    if (disposed) return;
    savePending({ ...pending, orderId: o.order_id });
    showOrder(o);
    describe(o);
    if (o.status !== "PENDING_INVENTORY") clearPending(o.order_id);
    await load();
  } catch (e) {
    if (!disposed) {
      error.value = message(e);
      if (
        e instanceof api.ApiError &&
        [
          "INSUFFICIENT_STOCK",
          "PRODUCT_NOT_FOUND",
          "IDEMPOTENCY_CONFLICT",
        ].includes(e.code || "")
      ) {
        memory = null;
        try {
          sessionStorage.removeItem("pending-order");
        } catch {
          /* best effort */
        }
      }
    }
  } finally {
    if (!disposed) busy.value = false;
  }
}
async function filter() {
  offset.value = 0;
  await load();
}
async function refresh() {
  error.value = "";
  await load();
}
onMounted(load);
onUnmounted(() => {
  disposed = true;
  loadVersion++;
  cancelPoll();
});
</script>
<template>
  <main>
    <header>
      <a class="brand" href="/">◈ ORDER STUDIO</a
      ><span class="tag">微服务协作演示</span>
    </header>
    <section class="hero">
      <p class="eyebrow">OPERATIONS / WORKSPACE</p>
      <h1>每笔订单，清晰有序。</h1>
      <p>查看可用库存，创建订单，跟进处理结果。</p>
    </section>
    <p v-if="error" role="alert" class="alert">
      {{ error }} <button @click="refresh">重试刷新</button>
    </p>
    <p v-if="notice" role="status" class="notice">{{ notice }}</p>
    <div class="layout">
      <section>
        <div class="section-title">
          <h2>
            商品库存 <small>{{ items.length }} 件商品</small>
          </h2>
          <button @click="refresh" :disabled="loading">刷新</button>
        </div>
        <p v-if="loading">正在加载…</p>
        <p v-else-if="!items.length">暂无商品</p>
        <div class="products">
          <button
            v-for="(p, i) in items"
            :key="p.product_id"
            :class="['product', { chosen: selected === p.product_id }]"
            @click="selected = p.product_id"
          >
            <span class="icon">{{ ["⌨", "◉", "▱"][i % 3] }}</span
            ><span class="sku">{{ p.sku }}</span
            ><strong>{{ p.name }}</strong
            ><span
              ><b>{{ p.available_qty }}</b> 件可用</span
            >
          </button>
        </div>
      </section>
      <aside>
        <p class="eyebrow">NEW ORDER</p>
        <h2>创建订单</h2>
        <form @submit.prevent="submit">
          <label
            >商品<select v-model="selected" required>
              <option v-for="p in items" :value="p.product_id">
                {{ p.name }}
              </option>
            </select></label
          ><label
            >数量<input
              v-model.number="quantity"
              type="number"
              min="1"
              max="99"
              step="1"
              required
          /></label>
          <p class="hint">库存以提交时的实际可用数量为准。</p>
          <button class="primary" :disabled="busy || !selected">
            {{ busy ? "正在提交…" : "确认创建订单 →" }}
          </button>
        </form>
      </aside>
    </div>
    <section class="orders">
      <div class="section-title">
        <h2>
          订单记录 <small>{{ total }} 笔</small>
        </h2>
        <select aria-label="订单状态" v-model="status" @change="filter">
          <option value="">全部状态</option>
          <option value="CONFIRMED">已确认</option>
          <option value="PENDING_INVENTORY">确认中</option>
          <option value="REJECTED">已拒绝</option>
        </select>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>订单编号</th>
              <th>商品</th>
              <th>数量</th>
              <th>状态</th>
              <th>创建时间</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="o in rows"
              :key="o.order_id"
              @click="showOrder(o)"
              tabindex="0"
              @keydown.enter="showOrder(o)"
            >
              <td>{{ o.order_id.slice(0, 8) }}</td>
              <td>{{ o.product_id }}</td>
              <td>{{ o.quantity }}</td>
              <td>
                <span :class="['badge', o.status]">{{
                  {
                    CONFIRMED: "已确认",
                    REJECTED: "已拒绝",
                    PENDING_INVENTORY: "确认中",
                  }[o.status]
                }}</span>
              </td>
              <td>{{ new Date(o.created_at).toLocaleString() }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!loading && !rows.length" class="empty">暂无符合条件的订单</p>
      <nav>
        <button
          :disabled="offset === 0"
          @click="
            offset -= 10;
            load();
          "
        >
          上一页</button
        ><span>{{ Math.floor(offset / 10) + 1 }}</span
        ><button
          :disabled="offset + 10 >= total"
          @click="
            offset += 10;
            load();
          "
        >
          下一页
        </button>
      </nav>
    </section>
    <section v-if="active" class="detail">
      <button @click="closeDetail">关闭详情 ×</button>
      <h2>订单详情</h2>
      <p>{{ active.order_id }}</p>
      <p>{{ labels[active.status] }} · {{ active.quantity }} 件</p>
      <p v-if="active.rejection_code">{{ active.rejection_code }}</p>
      <p v-if="active.needs_attention">
        结果仍待确认，请联系演示维护者恢复处理。
      </p>
      <button @click="refreshDetail">刷新状态</button>
    </section>
    <footer>ORDER STUDIO <span>订单与库存 · 本地演示环境</span></footer>
  </main>
</template>
