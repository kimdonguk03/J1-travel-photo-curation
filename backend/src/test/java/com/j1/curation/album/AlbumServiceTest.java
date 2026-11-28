package com.j1.curation.album;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import org.junit.jupiter.api.Test;

class AlbumServiceTest {

	@Test
	void safeNameKeepsPhotosAndDropsPaths() {
		assertEquals("IMG_0001.HEIC", AlbumService.safeName("DCIM/IMG_0001.HEIC"));
		assertEquals("a.jpg", AlbumService.safeName("C:\\Users\\x\\a.jpg"));
		assertEquals("b_c.png", AlbumService.safeName("b:c.png"));
		assertNull(AlbumService.safeName("clip.mp4"));
		assertNull(AlbumService.safeName(".hidden.jpg"));
		assertNull(AlbumService.safeName("../"));
		assertNull(AlbumService.safeName(null));
	}
}
