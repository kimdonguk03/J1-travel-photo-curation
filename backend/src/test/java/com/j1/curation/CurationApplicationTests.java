package com.j1.curation;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest(properties = {"spring.datasource.url=jdbc:h2:mem:j1test;DB_CLOSE_DELAY=-1", "j1.upload-root=build/test-uploads"})
class CurationApplicationTests {

	@Test
	void contextLoads() {
	}

}
