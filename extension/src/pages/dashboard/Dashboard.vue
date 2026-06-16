<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Box, Delete, Download, Refresh, Upload, View } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";

type PlatformTab = "all" | "1688" | "shopee";

type SkuRow = {
  spec_name: string;
  price: string;
  stock: string | number;
  sku_image?: string;
};

type ProductRow = {
  id: string;
  title: string;
  title_optimized?: string;
  source_title?: string;
  platform: "1688" | "Shopee" | "Unknown";
  base_price: string;
  main_images: string[];
  sku_list: SkuRow[];
  marketing_copy?: string;
  bullet_points?: string[];
  platform_tags?: string[];
  source_file?: string;
  updated_at?: string;
};

const API_BASE_URL = "http://localhost:8000";

const mockProducts: ProductRow[] = [
  {
    id: "mock-shopee",
    title: "Samyang Hot Chicken Ramen Multi-flavor Pack",
    title_optimized: "Korean Spicy Ramen Variety Pack - Bold Flavors",
    platform: "Shopee",
    base_price: "15.90-24.90",
    main_images: [
      "https://cf.shopee.com.my/file/sg-11134201-7rdxa-lx4p6y9w6wuzcc",
      "https://cf.shopee.com.my/file/sg-11134201-7rdwx-lx4p70ycskae4c",
    ],
    sku_list: [
      { spec_name: "Cheese", price: "15.90", stock: 88, sku_image: "" },
      { spec_name: "Carbonara", price: "18.90", stock: 64, sku_image: "" },
    ],
    marketing_copy:
      "A ready-to-list product package cleaned by EasyCollect. Review platform rules before publishing.",
    bullet_points: ["Full SKU matrix captured", "Main images prepared", "Shopee CSV export ready"],
    platform_tags: ["ramen", "korean snack", "instant noodles"],
    source_file: "mock",
    updated_at: new Date().toISOString(),
  },
  {
    id: "mock-1688",
    title: "1688 Laundry Mesh Bag Source Product",
    platform: "1688",
    base_price: "1.20-4.60",
    main_images: [],
    sku_list: [{ spec_name: "Large", price: "2.40", stock: 1200, sku_image: "" }],
    source_file: "mock",
    updated_at: new Date().toISOString(),
  },
];

const activeTab = ref<PlatformTab>("all");
const products = ref<ProductRow[]>([]);
const loading = ref(false);
const exporting = ref(false);
const deleting = ref(false);
const selectedRows = ref<ProductRow[]>([]);
const selectedProduct = ref<ProductRow | null>(null);
const detailVisible = ref(false);

const displayProducts = computed(() => (products.value.length ? products.value : mockProducts));

function productTitle(product: ProductRow): string {
  return product.title_optimized || product.title || product.source_title || "Untitled Product";
}

function productImage(product: ProductRow): string {
  return product.main_images?.[0] || "";
}

function platformTagType(product: ProductRow): "success" | "warning" | "info" {
  if (product.platform === "Shopee") return "warning";
  if (product.platform === "1688") return "success";
  return "info";
}

function platformQuery(tab: PlatformTab): string {
  if (tab === "shopee") return "?platform=shopee";
  if (tab === "1688") return "?platform=1688";
  return "";
}

async function loadProducts(): Promise<void> {
  loading.value = true;
  selectedRows.value = [];
  try {
    const response = await fetch(`${API_BASE_URL}/api/products${platformQuery(activeTab.value)}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = (await response.json()) as { products?: ProductRow[] };
    products.value = Array.isArray(data.products) ? data.products : [];
  } catch (error) {
    console.warn("[EasyCollect] failed to load products, using mock data:", error);
    ElMessage.warning("后端商品库暂不可用，当前展示 Mock 预览数据");
  } finally {
    loading.value = false;
  }
}

function handleTabChange(): void {
  void loadProducts();
}

function openDetail(product: ProductRow): void {
  selectedProduct.value = product;
  detailVisible.value = true;
}

function handleSelectionChange(rows: ProductRow[]): void {
  selectedRows.value = rows;
}

function selectedRealRows(): ProductRow[] {
  return selectedRows.value.filter((product) => product.source_file !== "mock");
}

function selectedPlatformSet(): Set<string> {
  return new Set(
    selectedRealRows()
      .map((product) => product.platform)
      .filter((platform) => platform && platform !== "Unknown"),
  );
}

async function exportSelectedProducts(): Promise<void> {
  const realRows = selectedRealRows();
  const productIds = realRows.map((product) => product.id);

  if (!productIds.length) {
    ElMessage.warning("请先选择要导出的商品");
    return;
  }

  if (activeTab.value === "all" && selectedPlatformSet().size > 1) {
    await ElMessageBox.alert(
      "禁止跨平台混合导出，请切换到具体平台 Tab 下进行批量操作！",
      "跨平台导出已拦截",
      { type: "warning", confirmButtonText: "我知道了" },
    );
    return;
  }

  exporting.value = true;
  try {
    const response = await fetch(`${API_BASE_URL}/api/export/bulk`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ product_ids: productIds }),
    });
    const data = (await response.json().catch(() => null)) as {
      download_url?: string;
      detail?: string;
    } | null;

    if (!response.ok || !data?.download_url) {
      throw new Error(data?.detail || `HTTP ${response.status}`);
    }

    window.open(data.download_url, "_blank", "noopener,noreferrer");
    ElMessage.success("批量导出任务已生成");
  } catch (error) {
    const message = error instanceof Error ? error.message : "批量导出失败";
    ElMessage.error(message);
  } finally {
    exporting.value = false;
  }
}

async function deleteSelectedProducts(): Promise<void> {
  const realRows = selectedRealRows();
  const productIds = realRows.map((product) => product.id);

  if (!productIds.length) {
    ElMessage.warning("请先选择要删除的商品");
    return;
  }

  await ElMessageBox.confirm(
    `确认删除选中的 ${productIds.length} 个商品吗？`,
    "批量删除商品",
    {
      confirmButtonText: "删除",
      cancelButtonText: "取消",
      type: "warning",
    },
  );

  deleting.value = true;
  try {
    const response = await fetch(`${API_BASE_URL}/api/products/bulk`, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ product_ids: productIds }),
    });
    const data = (await response.json().catch(() => null)) as {
      message?: string;
      detail?: string;
    } | null;

    if (!response.ok) {
      throw new Error(data?.detail || `HTTP ${response.status}`);
    }

    ElMessage.success(data?.message || "已删除选中商品");
    await loadProducts();
  } catch (error) {
    const message = error instanceof Error ? error.message : "批量删除失败";
    ElMessage.error(message);
  } finally {
    deleting.value = false;
  }
}

async function clearAllProducts(): Promise<void> {
  deleting.value = true;
  try {
    const response = await fetch(`${API_BASE_URL}/api/products/clear`, {
      method: "DELETE",
    });
    const data = (await response.json().catch(() => null)) as {
      message?: string;
      detail?: string;
    } | null;

    if (!response.ok) {
      throw new Error(data?.detail || `HTTP ${response.status}`);
    }

    ElMessage.success(data?.message || "商品库已清空");
    await loadProducts();
  } catch (error) {
    const message = error instanceof Error ? error.message : "清空商品库失败";
    ElMessage.error(message);
  } finally {
    deleting.value = false;
  }
}

function exportSingleProduct(product: ProductRow): void {
  selectedRows.value = [product];
  void exportSelectedProducts();
}

function publishProduct(): void {
  ElMessage.info("发布到平台将在 OpenAPI 或平台模板稳定后接入");
}

async function deleteProduct(product: ProductRow): Promise<void> {
  if (product.source_file === "mock") {
    ElMessage.info("Mock 数据无需删除");
    return;
  }

  await ElMessageBox.confirm(`确认删除「${productTitle(product)}」吗？`, "删除商品", {
    confirmButtonText: "删除",
    cancelButtonText: "取消",
    type: "warning",
  });

  const response = await fetch(`${API_BASE_URL}/api/products/${encodeURIComponent(product.id)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(`删除失败: HTTP ${response.status}`);
  }

  ElMessage.success("已删除");
  await loadProducts();
}

onMounted(() => {
  void loadProducts();
});
</script>

<template>
  <div class="dashboard-page">
    <el-container class="dashboard-shell">
      <el-header class="dashboard-header">
        <div class="brand-block">
          <div class="brand-mark">
            <el-icon><Box /></el-icon>
          </div>
          <div>
            <p class="brand-kicker">EasyCollect Console</p>
            <h1>采集商品管理</h1>
          </div>
        </div>
        <div class="header-actions">
          <el-button :icon="Refresh" @click="loadProducts">刷新</el-button>
          <el-button
            type="danger"
            plain
            :icon="Delete"
            :loading="deleting"
            @click="deleteSelectedProducts"
          >
            批量删除
          </el-button>
          <el-popconfirm
            title="确定要清空所有采集的数据吗？"
            confirm-button-text="清空"
            cancel-button-text="取消"
            width="248"
            @confirm="clearAllProducts"
          >
            <template #reference>
              <el-button type="danger" :icon="Delete" :loading="deleting">一键清空</el-button>
            </template>
          </el-popconfirm>
          <el-button
            type="primary"
            :icon="Download"
            :loading="exporting"
            @click="exportSelectedProducts"
          >
            批量导出选中商品 (ZIP)
          </el-button>
        </div>
      </el-header>

      <el-main class="dashboard-main">
        <el-tabs v-model="activeTab" class="platform-tabs" @tab-change="handleTabChange">
          <el-tab-pane label="全部商品" name="all" />
          <el-tab-pane label="1688 货源" name="1688" />
          <el-tab-pane label="Shopee 货源" name="shopee" />
        </el-tabs>

        <section class="summary-strip">
          <div>
            <span class="summary-label">商品数</span>
            <strong>{{ displayProducts.length }}</strong>
          </div>
          <div>
            <span class="summary-label">当前视图</span>
            <strong>{{ activeTab === "all" ? "全部平台" : activeTab }}</strong>
          </div>
          <div>
            <span class="summary-label">已选择</span>
            <strong>{{ selectedRows.length }}</strong>
          </div>
        </section>

        <el-table
          v-loading="loading"
          :data="displayProducts"
          row-key="id"
          border
          height="calc(100vh - 258px)"
          class="product-table"
          @selection-change="handleSelectionChange"
        >
          <el-table-column type="selection" width="46" />
          <el-table-column label="商品主图" width="108" align="center">
            <template #default="{ row }">
              <el-image
                v-if="productImage(row)"
                class="cover-image"
                :src="productImage(row)"
                :preview-src-list="row.main_images"
                preview-teleported
                fit="cover"
              />
              <div v-else class="image-empty">No Image</div>
            </template>
          </el-table-column>

          <el-table-column label="商品标题" min-width="360">
            <template #default="{ row }">
              <div class="title-cell">
                <strong>{{ productTitle(row) }}</strong>
                <span v-if="row.source_file">{{ row.source_file }}</span>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="来源平台" width="120" align="center">
            <template #default="{ row }">
              <el-tag :type="platformTagType(row)" effect="light">{{ row.platform }}</el-tag>
            </template>
          </el-table-column>

          <el-table-column prop="base_price" label="价格区间" width="150" />

          <el-table-column label="SKU" width="100" align="center">
            <template #default="{ row }">{{ row.sku_list?.length || 0 }}</template>
          </el-table-column>

          <el-table-column label="操作" width="292" fixed="right">
            <template #default="{ row }">
              <el-button size="small" :icon="View" @click="openDetail(row)">查看详情</el-button>
              <el-button size="small" :icon="Download" @click="exportSingleProduct(row)">
                导出 ZIP
              </el-button>
              <el-button size="small" type="primary" :icon="Upload" @click="publishProduct">
                发布
              </el-button>
              <el-button size="small" type="danger" plain @click="deleteProduct(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-main>
    </el-container>

    <el-dialog
      v-model="detailVisible"
      :title="selectedProduct ? productTitle(selectedProduct) : '商品详情'"
      width="980px"
      destroy-on-close
    >
      <el-tabs v-if="selectedProduct" type="border-card">
        <el-tab-pane label="基础信息">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="来源平台">
              <el-tag :type="platformTagType(selectedProduct)">{{ selectedProduct.platform }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="价格区间">
              {{ selectedProduct.base_price || "未识别" }}
            </el-descriptions-item>
            <el-descriptions-item label="SKU 数量">
              {{ selectedProduct.sku_list?.length || 0 }}
            </el-descriptions-item>
            <el-descriptions-item label="更新时间">
              {{ selectedProduct.updated_at || "-" }}
            </el-descriptions-item>
            <el-descriptions-item label="原始标题" :span="2">
              {{ selectedProduct.title || selectedProduct.source_title || "-" }}
            </el-descriptions-item>
          </el-descriptions>

          <div class="image-grid">
            <el-image
              v-for="image in selectedProduct.main_images"
              :key="image"
              class="gallery-image"
              :src="image"
              :preview-src-list="selectedProduct.main_images"
              preview-teleported
              fit="cover"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="AI 优化文案">
          <div class="copy-panel">
            <h3>{{ selectedProduct.title_optimized || selectedProduct.title }}</h3>
            <p>{{ selectedProduct.marketing_copy || "暂无 AI 优化文案，可使用 AI 深度采集生成。" }}</p>
            <el-divider />
            <h4>核心卖点</h4>
            <ul>
              <li v-for="point in selectedProduct.bullet_points || []" :key="point">{{ point }}</li>
              <li v-if="!selectedProduct.bullet_points?.length">暂无卖点数据</li>
            </ul>
            <h4>搜索标签</h4>
            <el-tag
              v-for="tag in selectedProduct.platform_tags || []"
              :key="tag"
              class="tag-item"
              effect="plain"
            >
              {{ tag }}
            </el-tag>
            <span v-if="!selectedProduct.platform_tags?.length" class="muted-text">暂无标签</span>
          </div>
        </el-tab-pane>

        <el-tab-pane label="变体(SKU)列表">
          <el-table :data="selectedProduct.sku_list" border height="360">
            <el-table-column label="变体图" width="86" align="center">
              <template #default="{ row }">
                <el-image
                  v-if="row.sku_image"
                  class="sku-image"
                  :src="row.sku_image"
                  :preview-src-list="[row.sku_image]"
                  preview-teleported
                  fit="cover"
                />
                <span v-else class="muted-text">无</span>
              </template>
            </el-table-column>
            <el-table-column prop="spec_name" label="规格名称" min-width="260" />
            <el-table-column prop="price" label="价格" width="120" />
            <el-table-column prop="stock" label="库存" width="120" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>
  </div>
</template>

<style scoped>
.dashboard-page {
  min-height: 100vh;
  background: #f4f6f8;
  color: #1f2937;
}

.dashboard-shell {
  min-height: 100vh;
}

.dashboard-header {
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid #d9e0e8;
  background: #ffffff;
}

.brand-block,
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: #ffffff;
  background: #2563eb;
  font-size: 22px;
}

.brand-kicker {
  margin: 0 0 3px;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
}

h1 {
  margin: 0;
  font-size: 20px;
  line-height: 1.2;
}

.dashboard-main {
  padding: 14px 20px 24px;
}

.platform-tabs {
  margin-bottom: 10px;
}

.summary-strip {
  display: grid;
  grid-template-columns: 160px 220px 160px;
  gap: 12px;
  margin-bottom: 14px;
}

.summary-strip > div {
  padding: 12px 14px;
  border: 1px solid #dbe3ed;
  border-radius: 8px;
  background: #ffffff;
}

.summary-label {
  display: block;
  margin-bottom: 5px;
  color: #64748b;
  font-size: 12px;
}

.product-table {
  border-radius: 8px;
  overflow: hidden;
}

.cover-image,
.image-empty {
  width: 64px;
  height: 64px;
  border-radius: 6px;
}

.image-empty {
  display: grid;
  place-items: center;
  border: 1px dashed #cbd5e1;
  color: #94a3b8;
  font-size: 11px;
}

.title-cell {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.title-cell strong {
  color: #111827;
  font-size: 14px;
  line-height: 1.35;
}

.title-cell span,
.muted-text {
  color: #64748b;
  font-size: 12px;
}

.image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(88px, 1fr));
  gap: 10px;
  margin-top: 16px;
}

.gallery-image {
  width: 88px;
  height: 88px;
  border-radius: 6px;
}

.copy-panel h3,
.copy-panel h4 {
  margin: 0 0 10px;
}

.copy-panel p {
  margin: 0;
  color: #374151;
  line-height: 1.7;
  white-space: pre-wrap;
}

.copy-panel ul {
  margin: 0 0 16px;
  padding-left: 18px;
}

.tag-item {
  margin-right: 8px;
  margin-bottom: 8px;
}

.sku-image {
  width: 46px;
  height: 46px;
  border-radius: 6px;
}
</style>
