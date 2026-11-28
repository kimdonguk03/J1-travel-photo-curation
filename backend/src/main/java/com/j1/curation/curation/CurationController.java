package com.j1.curation.curation;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import com.j1.curation.album.AlbumService;
import com.j1.curation.config.J1Properties;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

/**
 * 게스트 진입, 큐레이션 확정·보관함, 편집 실험 기록 내보내기.
 * 사용자는 X-J1-User 헤더(게스트 ID)로 구분합니다. 로컬·카카오·구글 로그인은 이 자리에 붙입니다.
 */
@RestController
public class CurationController {

	private final CurationRepository repo;
	private final AlbumService albums;
	private final J1Properties props;

	public CurationController(CurationRepository repo, AlbumService albums, J1Properties props) {
		this.repo = repo;
		this.albums = albums;
		this.props = props;
	}

	/** 게스트 ID 발급. 프론트엔드는 이 값을 저장해 두고 X-J1-User 헤더로 보냅니다. */
	@PostMapping("/api/auth/guest")
	public Map<String, String> guest() {
		return Map.of("userId", "guest-" + UUID.randomUUID());
	}

	public record CreateRequest(
			@NotBlank @Size(max = 200) String title,
			@NotBlank String albumId,
			@NotBlank @Pattern(regexp = "recommend|manual") String mode,
			@NotEmpty @Size(max = 50) List<String> finalIds,
			List<String> draftIds,
			Instant readyAt,
			Instant confirmedAt,
			@Min(1) @Max(5) Integer satisfaction) {
	}

	public record CurationView(Long id, String title, String mode, List<String> finalIds, List<String> photoNames,
			List<String> draftIds, String ruleVersion, Instant loadedAt, Instant readyAt, Instant confirmedAt,
			Integer satisfaction, Instant createdAt) {

		static CurationView of(Curation c) {
			return new CurationView(c.getId(), c.getTitle(), c.getMode(), split(c.getFinalIds()), split(c.getPhotoNames()),
					split(c.getDraftIds()), c.getRuleVersion(), c.getLoadedAt(), c.getReadyAt(), c.getConfirmedAt(),
					c.getSatisfaction(), c.getCreatedAt());
		}
	}

	/** 큐레이션 확정. 앨범 세션에서 원래 파일 이름과 불러오기 시각, 추천 초안을 채웁니다. */
	@PostMapping("/api/curations")
	public CurationView create(@RequestHeader("X-J1-User") String user, @Valid @RequestBody CreateRequest req) {
		AlbumService.AlbumRecord album = albums.record(req.albumId(), req.finalIds());
		List<String> draft = req.draftIds() != null ? req.draftIds() : album.draftIds();
		boolean rec = "recommend".equals(req.mode());
		Curation c = new Curation(owner(user), req.title(), req.albumId(), req.mode(),
				rec ? album.ruleVersion() : null,
				rec ? String.join(",", draft) : "",
				String.join(",", req.finalIds()), String.join("\n", album.names()),
				rec ? String.join("\n", albums.names(req.albumId(), draft)) : "",
				album.loadedAt(), req.readyAt(), req.confirmedAt() != null ? req.confirmedAt() : Instant.now(),
				req.satisfaction());
		return CurationView.of(repo.save(c));
	}

	/** 내 보관함 (최근순). */
	@GetMapping("/api/curations")
	public List<CurationView> list(@RequestHeader("X-J1-User") String user) {
		return repo.findByOwnerIdOrderByCreatedAtDesc(owner(user)).stream().map(CurationView::of).toList();
	}

	@GetMapping("/api/curations/{id}")
	public CurationView detail(@RequestHeader("X-J1-User") String user, @PathVariable Long id) {
		return repo.findByIdAndOwnerId(id, owner(user)).map(CurationView::of)
				.orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "큐레이션이 없습니다."));
	}

	/**
	 * 편집 실험 기록 CSV (모든 사용자). j1.admin-token을 설정하고 X-J1-Admin 헤더로 같은 값을 보내야 합니다.
	 * 사진 파일 이름은 넣지 않습니다.
	 */
	@GetMapping(path = "/api/admin/curations.csv", produces = "text/csv")
	public ResponseEntity<String> exportCsv(@RequestHeader(value = "X-J1-Admin", required = false) String token) {
		if (props.adminToken() == null || props.adminToken().isBlank() || !props.adminToken().equals(token)) {
			throw new ResponseStatusException(HttpStatus.FORBIDDEN, "관리자 토큰이 필요합니다.");
		}
		StringBuilder sb = new StringBuilder("﻿id,owner,mode,rule_version,loaded_at,ready_at,confirmed_at,"
				+ "total_sec,edit_sec,satisfaction,draft_ids,final_ids\r\n");
		for (Curation c : repo.findAll()) {
			sb.append(c.getId()).append(',').append(c.getOwnerId()).append(',').append(c.getMode()).append(',')
					.append(nz(c.getRuleVersion())).append(',').append(nz(c.getLoadedAt())).append(',')
					.append(nz(c.getReadyAt())).append(',').append(nz(c.getConfirmedAt())).append(',')
					.append(seconds(c.getLoadedAt(), c.getConfirmedAt())).append(',')
					.append(seconds(c.getReadyAt(), c.getConfirmedAt())).append(',')
					.append(nz(c.getSatisfaction())).append(',')
					.append('"').append(nz(c.getDraftIds())).append("\",\"").append(c.getFinalIds()).append("\"\r\n");
		}
		return ResponseEntity.ok().contentType(MediaType.parseMediaType("text/csv; charset=UTF-8")).body(sb.toString());
	}

	/**
	 * 편집 실험 분석용 전체 기록 (사진 파일 이름 포함). model/edit_eval.py가 읽습니다.
	 * 사진 이름이 들어 있으므로 관리자 토큰이 필요하고, 받은 파일은 저장소에 올리지 않습니다.
	 */
	@GetMapping("/api/admin/curations.json")
	public List<Map<String, Object>> exportJson(@RequestHeader(value = "X-J1-Admin", required = false) String token) {
		if (props.adminToken() == null || props.adminToken().isBlank() || !props.adminToken().equals(token)) {
			throw new ResponseStatusException(HttpStatus.FORBIDDEN, "관리자 토큰이 필요합니다.");
		}
		return repo.findAll().stream().map(c -> {
			Map<String, Object> m = new java.util.LinkedHashMap<>();
			m.put("id", c.getId());
			m.put("owner", c.getOwnerId());
			m.put("title", c.getTitle());
			m.put("mode", c.getMode());
			m.put("ruleVersion", c.getRuleVersion());
			m.put("loadedAt", nz(c.getLoadedAt()));
			m.put("readyAt", nz(c.getReadyAt()));
			m.put("confirmedAt", nz(c.getConfirmedAt()));
			m.put("satisfaction", c.getSatisfaction());
			m.put("draftNames", split(c.getDraftNames()));
			m.put("finalNames", split(c.getPhotoNames()));
			return m;
		}).toList();
	}

	private static String owner(String user) {
		if (user == null || user.isBlank() || user.length() > 64) {
			throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "X-J1-User 헤더가 필요합니다 (/api/auth/guest).");
		}
		return user.strip();
	}

	static List<String> split(String s) {
		return s == null || s.isBlank() ? List.of() : List.of(s.split(s.contains("\n") ? "\n" : ","));
	}

	private static String nz(Object o) {
		return o == null ? "" : o.toString();
	}

	private static String seconds(Instant from, Instant to) {
		return from == null || to == null ? "" : String.valueOf(java.time.Duration.between(from, to).toMillis() / 1000.0);
	}
}
