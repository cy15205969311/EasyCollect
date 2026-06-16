import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import { createApp } from "vue";

import Dashboard from "./Dashboard.vue";
import "../../styles.css";

createApp(Dashboard).use(ElementPlus).mount("#app");
