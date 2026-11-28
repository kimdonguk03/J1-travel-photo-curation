package com.j1.curation.curation;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;

public interface CurationRepository extends JpaRepository<Curation, Long> {

	List<Curation> findByOwnerIdOrderByCreatedAtDesc(String ownerId);

	Optional<Curation> findByIdAndOwnerId(Long id, String ownerId);
}
