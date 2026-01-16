package com.example.gestureOSManager.controller;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
@CrossOrigin(origins = "http://localhost:5173")
public class PairingController {

  @Value("${gestureos.pairing.httpPort:8081}")
  private int httpPort;

  @Value("${gestureos.pairing.udpPort:39500}")
  private int udpPort;

  @Value("${gestureos.pairing.name:PC}")
  private String name;

  @GetMapping("/pairing")
  public Map<String, Object> pairing() {
    List<String> candidates = findIPv4Candidates();
    String pc = candidates.isEmpty() ? "" : candidates.get(0);

    return Map.of(
      "pc", pc,
      "httpPort", httpPort,
      "udpPort", udpPort,
      "name", (name == null || name.isBlank()) ? "PC" : name,
      "candidates", candidates
    );
  }

  // ------------------------------------------------------------
  // LAN IPv4 자동 탐지 (Loopback/169.254 제외, private 우선)
  // ------------------------------------------------------------
  private static List<String> findIPv4Candidates() {
    List<IpCandidate> buf = new ArrayList<>();

    try {
      Enumeration<NetworkInterface> ifaces = NetworkInterface.getNetworkInterfaces();
      while (ifaces.hasMoreElements()) {
        NetworkInterface nif = ifaces.nextElement();

        try {
          if (!nif.isUp() || nif.isLoopback()) continue;
        } catch (Exception ignore) {}

        String ifName = safe(nif.getName());
        String disp = safe(nif.getDisplayName());

        Enumeration<InetAddress> addrs = nif.getInetAddresses();
        while (addrs.hasMoreElements()) {
          InetAddress a = addrs.nextElement();
          if (!(a instanceof Inet4Address)) continue;

          String ip = a.getHostAddress();
          if (ip.startsWith("127.")) continue;
          if (ip.startsWith("169.254.")) continue;
          if (a.isLoopbackAddress()) continue;

          int score = 0;
          if (a.isSiteLocalAddress()) score += 100;
          score += scoreByInterfaceName(ifName, disp);

          buf.add(new IpCandidate(ip, score));
        }
      }
    } catch (Exception ignore) {}

    buf.sort((x, y) -> Integer.compare(y.score, x.score));

    Set<String> uniq = new LinkedHashSet<>();
    for (IpCandidate c : buf) uniq.add(c.ip);

    return new ArrayList<>(uniq);
  }

  private static int scoreByInterfaceName(String name, String display) {
    String s = (name + " " + display).toLowerCase(Locale.ROOT);
    int score = 0;

    if (s.contains("wi-fi") || s.contains("wifi") || s.contains("wireless") || s.contains("wlan")) score += 30;
    if (s.contains("ethernet") || s.contains("eth")) score += 20;

    if (s.contains("virtual") || s.contains("vmware") || s.contains("hyper-v") || s.contains("vbox")) score -= 60;
    if (s.contains("loopback") || s.contains("tunnel") || s.contains("teredo")) score -= 60;

    return score;
  }

  private static String safe(String s) { return s == null ? "" : s; }

  private static class IpCandidate {
    final String ip;
    final int score;
    IpCandidate(String ip, int score) { this.ip = ip; this.score = score; }
  }
}
