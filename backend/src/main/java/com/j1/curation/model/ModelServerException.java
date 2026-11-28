package com.j1.curation.model;

import org.springframework.http.HttpStatus;

/** 모델 서버가 오류를 돌려줬거나 연결할 수 없을 때. 메시지는 화면에 그대로 보여도 되는 한국어입니다. */
public class ModelServerException extends RuntimeException {

	private final HttpStatus status;

	public ModelServerException(HttpStatus status, String message) {
		super(message);
		this.status = status;
	}

	public HttpStatus status() {
		return status;
	}
}
