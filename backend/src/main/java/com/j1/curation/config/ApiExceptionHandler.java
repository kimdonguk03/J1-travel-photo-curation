package com.j1.curation.config;

import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.server.ResponseStatusException;

import com.j1.curation.model.ModelServerException;

/** 오류 응답을 모델 서버와 같은 형식 {"detail": "..."}으로 맞춥니다. */
@RestControllerAdvice
public class ApiExceptionHandler {

	@ExceptionHandler(ModelServerException.class)
	ResponseEntity<Map<String, String>> model(ModelServerException e) {
		return ResponseEntity.status(e.status()).body(Map.of("detail", e.getMessage()));
	}

	@ExceptionHandler(ResponseStatusException.class)
	ResponseEntity<Map<String, String>> status(ResponseStatusException e) {
		String reason = e.getReason() != null ? e.getReason() : e.getStatusCode().toString();
		return ResponseEntity.status(e.getStatusCode()).body(Map.of("detail", reason));
	}

	@ExceptionHandler(MethodArgumentNotValidException.class)
	ResponseEntity<Map<String, String>> invalid(MethodArgumentNotValidException e) {
		String msg = e.getBindingResult().getFieldErrors().stream()
				.map(f -> f.getField() + ": " + f.getDefaultMessage()).findFirst().orElse("요청 형식이 틀렸습니다.");
		return ResponseEntity.badRequest().body(Map.of("detail", msg));
	}

	@ExceptionHandler(org.springframework.web.bind.MissingRequestHeaderException.class)
	ResponseEntity<Map<String, String>> header(org.springframework.web.bind.MissingRequestHeaderException e) {
		if ("X-J1-User".equals(e.getHeaderName())) {
			return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
					.body(Map.of("detail", "X-J1-User 헤더가 필요합니다 (/api/auth/guest)."));
		}
		return ResponseEntity.badRequest().body(Map.of("detail", e.getHeaderName() + " 헤더가 필요합니다."));
	}

	@ExceptionHandler(MaxUploadSizeExceededException.class)
	ResponseEntity<Map<String, String>> tooLarge(MaxUploadSizeExceededException e) {
		return ResponseEntity.status(HttpStatus.CONTENT_TOO_LARGE)
				.body(Map.of("detail", "업로드 크기 한도를 넘었습니다. 사진 수를 줄여 다시 올려 주세요."));
	}
}
