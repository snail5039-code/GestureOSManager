package com.example.gestureOSManager.mapper;

import java.util.List;
import org.apache.ibatis.annotations.*;

@Mapper
public interface LearnerProfileMapper {

  @Select("""
      SELECT model_json
      FROM gestureos_learner_profile
      WHERE member_id = #{memberId} AND profile_name = #{profileName}
      """)
  String findModel(@Param("memberId") Long memberId, @Param("profileName") String profileName);

  @Insert("""
      INSERT INTO gestureos_learner_profile(member_id, profile_name, model_json, updated_at)
      VALUES(#{memberId}, #{profileName}, #{modelJson}, now())
      ON CONFLICT (member_id, profile_name)
      DO UPDATE SET model_json = EXCLUDED.model_json, updated_at = now()
      """)
  int upsert(@Param("memberId") Long memberId,
             @Param("profileName") String profileName,
             @Param("modelJson") String modelJson);

  @Delete("""
      DELETE FROM gestureos_learner_profile
      WHERE member_id = #{memberId} AND profile_name = #{profileName}
      """)
  int delete(@Param("memberId") Long memberId, @Param("profileName") String profileName);

  @Select("""
      SELECT profile_name
      FROM gestureos_learner_profile
      WHERE member_id = #{memberId}
      ORDER BY profile_name
      """)
  List<String> listProfiles(@Param("memberId") Long memberId);
}
