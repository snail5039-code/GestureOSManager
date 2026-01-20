package com.example.gestureOSManager.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * MediaPipe hand landmark payload item.
 *
 * Python agent (hands_agent.py) sends:
 *   {"x": float, "y": float, "z": float}
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class Landmark3D {
  private Double x;
  private Double y;
  private Double z;
}
