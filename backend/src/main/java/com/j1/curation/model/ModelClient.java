package com.j1.curation.model;

import java.util.List;

import org.springframework.http.HttpStatus;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import com.j1.curation.config.J1Properties;
import com.j1.curation.model.ModelDtos.ErrorBody;
import com.j1.curation.model.ModelDtos.Health;
import com.j1.curation.model.ModelDtos.ModelPhoto;
import com.j1.curation.model.ModelDtos.RecommendRequest;
import com.j1.curation.model.ModelDtos.RecommendResult;
import com.j1.curation.model.ModelDtos.ScanRequest;
import com.j1.curation.model.ModelDtos.ScanResult;

/** 모델 서버 HTTP 클라이언트. 오류는 ModelServerException(상태 코드 + 한국어 안내)으로 바꿉니다. */
@Component
public class ModelClient {

	private final RestClient http;

	public ModelClient(J1Properties props) {
		SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
		factory.setConnectTimeout(java.time.Duration.ofSeconds(5));
		factory.setReadTimeout(props.modelTimeout());
		this.http = RestClient.builder().baseUrl(props.modelServerUrl()).requestFactory(factory).build();
	}

	public Health health() {
		return call(() -> http.get().uri("/health").retrieve().body(Health.class));
	}

	public ScanResult scan(String folder) {
		return call(() -> http.post().uri("/scan").body(new ScanRequest(folder)).retrieve().body(ScanResult.class));
	}

	public RecommendResult recommend(List<ModelPhoto> photos, Integer k) {
		return call(() -> http.post().uri("/recommend").body(new RecommendRequest(photos, k)).retrieve()
				.body(RecommendResult.class));
	}

	/** 정방향 JPEG 바이트. size는 긴 변 픽셀(목록 512, 큰 미리보기 1600). */
	public byte[] thumb(String path, int size) {
		return call(() -> http.get().uri(u -> u.path("/thumb").queryParam("path", path).queryParam("size", size).build())
				.retrieve().body(byte[].class));
	}

	private <T> T call(java.util.function.Supplier<T> request) {
		try {
			return request.get();
		} catch (RestClientResponseException e) {
			String message;
			try {
				ErrorBody body = e.getResponseBodyAs(ErrorBody.class);
				message = body != null ? body.message() : e.getStatusText();
			} catch (RuntimeException parse) {
				message = e.getStatusText();
			}
			throw new ModelServerException(HttpStatus.valueOf(e.getStatusCode().value()), message);
		} catch (ResourceAccessException e) {
			throw new ModelServerException(HttpStatus.SERVICE_UNAVAILABLE,
					"모델 서버에 연결할 수 없습니다. model/server.py가 실행 중인지 확인하세요.");
		}
	}
}
