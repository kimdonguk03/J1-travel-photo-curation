package com.j1.curation.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/** 개발 중 프론트엔드 개발 서버(다른 포트)에서 API를 부를 수 있게 합니다. */
@Configuration
public class WebConfig implements WebMvcConfigurer {

	private final J1Properties props;

	public WebConfig(J1Properties props) {
		this.props = props;
	}

	@Override
	public void addCorsMappings(CorsRegistry registry) {
		registry.addMapping("/api/**")
				.allowedOrigins(props.corsOrigins().toArray(String[]::new))
				.allowedMethods("GET", "POST", "PUT", "DELETE")
				.allowedHeaders("*");
	}
}
