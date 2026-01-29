// src/api/trainClient.js
import axios from "axios";

// 8080(매니저)로 고정: file:// 환경에서는 절대경로 필요
const origin = window.location.protocol === "file:" ? "http://127.0.0.1:8080" : "";

export const trainApi = axios.create({
  baseURL: origin + "/api",   // 최종: http://127.0.0.1:8080/api
  timeout: 8000,
  headers: { Accept: "application/json" },
});
