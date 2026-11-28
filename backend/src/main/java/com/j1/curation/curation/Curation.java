package com.j1.curation.curation;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;

/**
 * 확정한 큐레이션 한 건 (보관함). 편집 실험 기록도 함께 남깁니다:
 * 초안 사진, 최종 사진, 불러오기 시작·화면 준비·확정 시각, 모드, 만족도.
 * 사진 ID 목록은 쉼표로 이어 저장합니다 (p0001,p0005,...).
 */
@Entity
@Table(name = "curation", indexes = @Index(columnList = "ownerId"))
public class Curation {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(nullable = false, length = 64)
	private String ownerId;           // 게스트 ID 또는 사용자 ID

	@Column(nullable = false, length = 200)
	private String title;

	@Column(length = 64)
	private String albumId;

	@Column(nullable = false, length = 16)
	private String mode;              // recommend | manual

	@Column(length = 120)
	private String ruleVersion;       // 추천 모드일 때 모델 rule_version

	@Column(columnDefinition = "TEXT")
	private String draftIds;          // 추천 초안 (manual이면 빈 값)

	@Column(columnDefinition = "TEXT", nullable = false)
	private String finalIds;          // 확정한 사진

	@Column(columnDefinition = "TEXT")
	private String photoNames;        // 확정한 사진의 원래 파일 이름 (보관함 표시용)

	private Instant loadedAt;         // 불러오기 시작
	private Instant readyAt;          // 편집 화면 준비 (추천 모드는 추천 응답 시각)
	private Instant confirmedAt;      // 확정
	private Integer satisfaction;     // 1~5, 선택

	@Column(nullable = false)
	private Instant createdAt = Instant.now();

	protected Curation() {
	}

	public Curation(String ownerId, String title, String albumId, String mode, String ruleVersion, String draftIds,
			String finalIds, String photoNames, Instant loadedAt, Instant readyAt, Instant confirmedAt,
			Integer satisfaction) {
		this.ownerId = ownerId;
		this.title = title;
		this.albumId = albumId;
		this.mode = mode;
		this.ruleVersion = ruleVersion;
		this.draftIds = draftIds;
		this.finalIds = finalIds;
		this.photoNames = photoNames;
		this.loadedAt = loadedAt;
		this.readyAt = readyAt;
		this.confirmedAt = confirmedAt;
		this.satisfaction = satisfaction;
	}

	public Long getId() { return id; }
	public String getOwnerId() { return ownerId; }
	public String getTitle() { return title; }
	public String getAlbumId() { return albumId; }
	public String getMode() { return mode; }
	public String getRuleVersion() { return ruleVersion; }
	public String getDraftIds() { return draftIds; }
	public String getFinalIds() { return finalIds; }
	public String getPhotoNames() { return photoNames; }
	public Instant getLoadedAt() { return loadedAt; }
	public Instant getReadyAt() { return readyAt; }
	public Instant getConfirmedAt() { return confirmedAt; }
	public Integer getSatisfaction() { return satisfaction; }
	public Instant getCreatedAt() { return createdAt; }
}
