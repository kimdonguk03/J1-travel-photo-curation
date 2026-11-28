package com.j1.curation.config;

import java.nio.file.Path;
import java.time.Duration;
import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** application.properties의 j1.* 설정. 값이 없으면 아래 기본값을 씁니다. */
@ConfigurationProperties(prefix = "j1")
public record J1Properties(
		String modelServerUrl,
		Duration modelTimeout,
		Path uploadRoot,
		Duration uploadTtl,
		boolean allowLocalFolder,
		List<String> corsOrigins,
		String adminToken) {

	public J1Properties {
		modelServerUrl = modelServerUrl == null ? "http://127.0.0.1:8001" : modelServerUrl;
		modelTimeout = modelTimeout == null ? Duration.ofMinutes(5) : modelTimeout;
		uploadRoot = uploadRoot == null ? Path.of("data", "uploads") : uploadRoot;
		uploadTtl = uploadTtl == null ? Duration.ofHours(6) : uploadTtl;
		corsOrigins = corsOrigins == null ? List.of() : corsOrigins;
	}
}
