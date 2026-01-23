package com.example.gestureOSManager.dto;

import java.util.Map;

import com.fasterxml.jackson.annotation.JsonInclude;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@JsonInclude(JsonInclude.Include.NON_NULL)
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AgentCommand {

	private CommandType type;
	private ModeType mode;

	private Map<String, Object> settings;

//✅ NEW
	private Double gain;

	private Boolean enabled;

	// ✅ training payload
	private Map<String, Object> payload;

	// =========================
	// Base commands
	// =========================
	public static AgentCommand enable() {
		return AgentCommand.builder().type(CommandType.ENABLE).build();
	}

	public static AgentCommand disable() {
		return AgentCommand.builder().type(CommandType.DISABLE).build();
	}

	public static AgentCommand ofMode(ModeType mode) {
		return AgentCommand.builder().type(CommandType.SET_MODE).mode(mode).build();
	}

	public static AgentCommand ofSettings(Map<String, Object> settings) {
		return AgentCommand.builder().type(CommandType.UPDATE_SETTINGS).settings(settings).build();
	}

	public static AgentCommand preview(boolean enabled) {
		return AgentCommand.builder().type(CommandType.SET_PREVIEW).enabled(enabled).build();
	}

	// ✅ 프론트 “잠금” 토글용
	public static AgentCommand lock(boolean enabled) {
		return AgentCommand.builder().type(CommandType.SET_LOCK).enabled(enabled).build();
	}

	// =========================
	// ✅ Training commands
	// =========================
	public static AgentCommand trainCapture(String hand, String label, double seconds, int hz) {
		return AgentCommand.builder().type(CommandType.TRAIN_CAPTURE)
				.payload(Map.of("hand", hand, "label", label, "seconds", seconds, "hz", hz)).build();
	}

	public static AgentCommand trainTrain() {
		return AgentCommand.builder().type(CommandType.TRAIN_TRAIN).build();
	}

	public static AgentCommand trainEnable(boolean enabled) {
		return AgentCommand.builder().type(CommandType.TRAIN_ENABLE).enabled(enabled).build();
	}

	public static AgentCommand trainReset() {
		return AgentCommand.builder().type(CommandType.TRAIN_RESET).build();
	}

	// =========================
	// ✅ Profile commands
	// =========================
	public static AgentCommand trainSetProfile(String profile) {
		return AgentCommand.builder().type(CommandType.TRAIN_SET_PROFILE).payload(Map.of("profile", profile)).build();
	}

	public static AgentCommand trainProfileCreate(String profile, boolean copy) {
		return AgentCommand.builder().type(CommandType.TRAIN_PROFILE_CREATE)
				.payload(Map.of("profile", profile, "copy", copy)).build();
	}

	public static AgentCommand trainProfileDelete(String profile) {
		return AgentCommand.builder().type(CommandType.TRAIN_PROFILE_DELETE).payload(Map.of("profile", profile))
				.build();
	}

	public static AgentCommand trainProfileRename(String from, String to) {
		return AgentCommand.builder().type(CommandType.TRAIN_PROFILE_RENAME).payload(Map.of("from", from, "to", to))
				.build();
	}

	public static AgentCommand trainRollback() {
		return AgentCommand.builder().type(CommandType.TRAIN_ROLLBACK).build();
	}
}
