// src/api/pairingClient.js
import axios from "axios";
import { pairingApiBaseURL, pairingApiUrl } from "../runtime/endpoints";

// axios 버전
const api = axios.create({
  baseURL: pairingApiBaseURL(), // file:// => http://127.0.0.1:8080/api
  timeout: 8000,
  headers: { Accept: "application/json" },
});

// pairing 정보 가져오기 (PC / udpPort / candidates / httpPort 등)
export async function fetchPairing() {
  // ✅ GET /api/pairing
  const r = await api.get("/pairing");
  return r?.data;
}

// fetch 버전이 필요하면
export async function fetchPairingByFetch() {
  const r = await fetch(pairingApiUrl("pairing"));
  if (!r.ok) throw new Error(`pairing failed: ${r.status}`);
  return await r.json();
}
