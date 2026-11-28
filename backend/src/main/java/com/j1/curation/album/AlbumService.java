package com.j1.curation.album;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Stream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

import com.j1.curation.album.AlbumViews.AlbumView;
import com.j1.curation.album.AlbumViews.ClusterView;
import com.j1.curation.album.AlbumViews.FailedView;
import com.j1.curation.album.AlbumViews.PhotoView;
import com.j1.curation.album.AlbumViews.RecommendView;
import com.j1.curation.config.J1Properties;
import com.j1.curation.model.ModelClient;
import com.j1.curation.model.ModelDtos.Cluster;
import com.j1.curation.model.ModelDtos.ModelPhoto;
import com.j1.curation.model.ModelDtos.RecommendResult;
import com.j1.curation.model.ModelDtos.ScanResult;

/** 앨범 불러오기(업로드·서버 폴더), 썸네일, 추천, 원본 내려받기, 세션 정리. */
@Service
public class AlbumService {

	private static final Logger log = LoggerFactory.getLogger(AlbumService.class);
	private static final Set<String> PHOTO_EXTS = Set.of("jpg", "jpeg", "png", "heic", "heif", "webp");

	private final ModelClient model;
	private final J1Properties props;
	private final Map<String, AlbumSession> albums = new ConcurrentHashMap<>();

	public AlbumService(ModelClient model, J1Properties props) {
		this.model = model;
		this.props = props;
	}

	// ------------------------------------------------------------------
	// 불러오기
	// ------------------------------------------------------------------

	/** 업로드한 원본을 세션 폴더에 저장하고 스캔합니다. EXIF(촬영 시각)가 남도록 원본 그대로 받아야 합니다. */
	public AlbumView upload(List<MultipartFile> files, boolean consent) {
		if (!consent) {
			throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
					"사진을 서버에 올리고 처리한 뒤 지우는 것에 동의해야 합니다 (consent=true).");
		}
		if (files == null || files.isEmpty()) {
			throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "사진 파일이 없습니다.");
		}
		Instant started = Instant.now();
		String id = UUID.randomUUID().toString();
		Path dir = props.uploadRoot().toAbsolutePath().normalize().resolve(id);
		try {
			Files.createDirectories(dir);
			Set<String> used = new HashSet<>();
			int saved = 0;
			for (MultipartFile f : files) {
				String name = safeName(f.getOriginalFilename());
				if (name == null) {
					continue;  // 사진이 아닌 파일은 건너뜁니다
				}
				name = unique(name, used);
				try (InputStream in = f.getInputStream()) {
					Files.copy(in, dir.resolve(name));
				}
				saved++;
			}
			if (saved == 0) {
				deleteDir(dir);
				throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
						"사진 파일이 없습니다. 지원 형식: " + String.join(", ", PHOTO_EXTS));
			}
		} catch (IOException e) {
			deleteDir(dir);
			throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "업로드한 사진을 저장하지 못했습니다.");
		}
		try {
			return open(id, dir, true, started);
		} catch (RuntimeException e) {
			deleteDir(dir);
			throw e;
		}
	}

	/** 서버 PC의 폴더를 그대로 엽니다 (시연 PC 전용, j1.allow-local-folder=true일 때만). */
	public AlbumView loadFolder(String folder) {
		if (!props.allowLocalFolder()) {
			throw new ResponseStatusException(HttpStatus.FORBIDDEN, "서버 폴더로 불러오기가 꺼져 있습니다. 사진을 업로드해 주세요.");
		}
		Instant started = Instant.now();
		return open(UUID.randomUUID().toString(), Path.of(folder), false, started);
	}

	private AlbumView open(String id, Path dir, boolean uploaded, Instant started) {
		ScanResult scan = model.scan(dir.toString());
		if (scan.photos().isEmpty()) {
			throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "읽을 수 있는 사진이 없습니다.");
		}
		AlbumSession s = new AlbumSession(id, dir, uploaded, started, scan.photos(), scan.video_count(), scan.failed());
		albums.put(id, s);
		return view(s);
	}

	public AlbumView get(String albumId) {
		return view(session(albumId));
	}

	// ------------------------------------------------------------------
	// 썸네일·추천·내려받기
	// ------------------------------------------------------------------

	public byte[] thumb(String albumId, String photoId, int size) {
		AlbumSession s = session(albumId);
		ModelPhoto p = s.photo(photoId);
		if (p == null) {
			throw new ResponseStatusException(HttpStatus.NOT_FOUND, "사진이 없습니다: " + photoId);
		}
		return model.thumb(p.path(), size);
	}

	/** 추천 모드에서만 부릅니다. k를 생략하면 min(10, 읽을 수 있는 사진 수). */
	public RecommendView recommend(String albumId, Integer k) {
		AlbumSession s = session(albumId);
		RecommendResult r = model.recommend(List.copyOf(s.photos.values()), k);
		s.recommend = r;
		Set<String> draft = Set.copyOf(r.draft_ids());
		List<ClusterView> clusters = new ArrayList<>();
		List<String> missing = new ArrayList<>();
		for (Cluster c : r.clusters()) {
			clusters.add(new ClusterView(c.cluster_id(), c.photo_ids(), c.representative_id()));
			if (c.photo_ids().stream().noneMatch(draft::contains)) {
				missing.add(c.cluster_id());
			}
		}
		return new RecommendView(albumId, r.draft_ids(), clusters, missing, r.rule_version(), Instant.now().toString());
	}

	/** 큐레이션 확정에 필요한 앨범 정보. names는 finalIds 순서의 원래 파일 이름. */
	public record AlbumRecord(List<String> names, Instant loadedAt, List<String> draftIds, String ruleVersion) {
	}

	public AlbumRecord record(String albumId, List<String> finalIds) {
		AlbumSession s = session(albumId);
		if (new HashSet<>(finalIds).size() != finalIds.size()) {
			throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "같은 사진이 두 번 들어 있습니다.");
		}
		requirePhotos(albumId, finalIds);
		List<String> names = finalIds.stream().map(pid -> s.photo(pid).relpath()).toList();
		RecommendResult r = s.recommend;
		return new AlbumRecord(names, s.loadedAt, r == null ? List.of() : r.draft_ids(),
				r == null ? null : r.rule_version());
	}

	/** 사진 ID가 모두 이 앨범에 있는지 확인합니다 (내려받기를 시작하기 전에). */
	public void requirePhotos(String albumId, List<String> photoIds) {
		AlbumSession s = session(albumId);
		for (String pid : photoIds) {
			if (s.photo(pid) == null) {
				throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "사진이 없습니다: " + pid);
			}
		}
	}

	/** 고른 사진 원본을 zip으로 씁니다. 파일 이름 앞에 촬영순 번호를 붙입니다. */
	public void zip(String albumId, List<String> photoIds, OutputStream out) throws IOException {
		AlbumSession s = session(albumId);
		List<ModelPhoto> chosen = new ArrayList<>();
		for (String pid : photoIds) {
			ModelPhoto p = s.photo(pid);
			if (p == null) {
				throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "사진이 없습니다: " + pid);
			}
			chosen.add(p);
		}
		chosen.sort(Comparator.comparing((ModelPhoto p) -> p.taken_at() == null ? "~" : p.taken_at())
				.thenComparing(ModelPhoto::relpath));
		try (ZipOutputStream zip = new ZipOutputStream(out)) {
			int n = 1;
			for (ModelPhoto p : chosen) {
				String base = Path.of(p.relpath()).getFileName().toString();
				zip.putNextEntry(new ZipEntry(String.format("%02d_%s", n++, base)));
				Files.copy(Path.of(p.path()), zip);
				zip.closeEntry();
			}
		}
	}

	/** 앨범 세션을 닫습니다. 업로드한 앨범이면 사진 폴더를 지웁니다. */
	public void delete(String albumId) {
		AlbumSession s = albums.remove(albumId);
		if (s == null) {
			throw new ResponseStatusException(HttpStatus.NOT_FOUND, "앨범이 없습니다: " + albumId);
		}
		if (s.uploaded) {
			deleteDir(s.root);
		}
	}

	/** 오래 쓰지 않은 업로드 앨범을 지웁니다 (j1.upload-ttl). 30분마다 실행. */
	@Scheduled(fixedDelay = 30 * 60 * 1000L, initialDelay = 60 * 1000L)
	public void cleanup() {
		Instant limit = Instant.now().minus(props.uploadTtl());
		albums.values().removeIf(s -> {
			if (s.lastUsed.isBefore(limit)) {
				if (s.uploaded) {
					deleteDir(s.root);
				}
				log.info("앨범 세션 정리: {}", s.id);
				return true;
			}
			return false;
		});
	}

	// ------------------------------------------------------------------
	// 내부
	// ------------------------------------------------------------------

	AlbumSession session(String albumId) {
		AlbumSession s = albums.get(albumId);
		if (s == null) {
			throw new ResponseStatusException(HttpStatus.NOT_FOUND, "앨범이 없거나 시간이 지나 정리됐습니다. 다시 불러와 주세요.");
		}
		s.lastUsed = Instant.now();
		return s;
	}

	private static AlbumView view(AlbumSession s) {
		List<PhotoView> photos = s.photos.values().stream()
				.map(p -> new PhotoView(p.photo_id(), p.relpath(), p.taken_at())).toList();
		List<FailedView> failed = s.failed.stream().map(f -> new FailedView(f.relpath(), f.reason())).toList();
		return new AlbumView(s.id, photos, s.videoCount, failed, s.loadedAt.toString());
	}

	/** 경로 성분을 떼고, 사진 확장자가 아니면 null. */
	static String safeName(String original) {
		if (original == null || original.isBlank()) {
			return null;
		}
		String name = original.replace('\\', '/');
		name = name.substring(name.lastIndexOf('/') + 1).replaceAll("[\\x00-\\x1f<>:\"|?*]", "_").strip();
		int dot = name.lastIndexOf('.');
		if (dot <= 0 || name.startsWith(".")) {
			return null;
		}
		String ext = name.substring(dot + 1).toLowerCase(Locale.ROOT);
		return PHOTO_EXTS.contains(ext) ? name : null;
	}

	private static String unique(String name, Set<String> used) {
		String candidate = name;
		int dot = name.lastIndexOf('.');
		for (int i = 1; !used.add(candidate.toLowerCase(Locale.ROOT)); i++) {
			candidate = name.substring(0, dot) + "(" + i + ")" + name.substring(dot);
		}
		return candidate;
	}

	private static void deleteDir(Path dir) {
		if (dir == null || !Files.exists(dir)) {
			return;
		}
		try (Stream<Path> walk = Files.walk(dir)) {
			walk.sorted(Comparator.reverseOrder()).forEach(p -> {
				try {
					Files.deleteIfExists(p);
				} catch (IOException e) {
					log.warn("지우지 못한 파일: {}", p);
				}
			});
		} catch (IOException e) {
			log.warn("폴더를 지우지 못했습니다: {}", dir);
		}
	}
}
