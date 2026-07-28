#ifndef GAME_RULESETIDENTITY_H_
#define GAME_RULESETIDENTITY_H_

#include "../core/global.h"
#include "../external/nlohmann_json/json.hpp"

struct RulesetIdentityError final : public StringError {
  std::string code;

  RulesetIdentityError(const std::string& errorCode, const std::string& errorMessage);
  const std::string& getCode() const;
};

class RulesetIdentity {
public:
  static const std::string PUBLIC_RULESET_ID;
  static const std::string PUBLIC_SEMANTIC_VERSION;
  static const std::string PUBLIC_DESCRIPTOR_SHA256;
  static const std::string DESCRIPTOR_SCHEMA_ID;
  static const std::string DESCRIPTOR_SCHEMA_SHA256;
  static const std::string CANONICALIZATION_PROFILE;

  static constexpr int64_t SAFE_INTEGER_MIN = -9007199254740991LL;
  static constexpr int64_t SAFE_INTEGER_MAX = 9007199254740991LL;

  static nlohmann::json parseRestrictedJson(const std::string& rawJson);
  static std::string canonicalizeRestrictedJson(const char* rawJson);
  static std::string canonicalizeRestrictedJson(const std::string& rawJson);
  static std::string canonicalizeRestrictedJson(const nlohmann::json& value);
  static std::string sha256Hex(const std::string& bytes);

  static RulesetIdentity fromDescriptorJson(
    const std::string& descriptorJson,
    const std::string& descriptorSchemaJson,
    bool requirePublic = true
  );

  const std::string& getRulesetId() const;
  const std::string& getSemanticVersion() const;
  const std::string& getDescriptorSha256() const;
  const std::string& getCanonicalDescriptorBytes() const;

  nlohmann::json toJson() const;

  bool operator==(const RulesetIdentity& other) const;
  bool operator!=(const RulesetIdentity& other) const;

private:
  std::string rulesetId;
  std::string semanticVersion;
  std::string descriptorSha256;
  std::string canonicalDescriptorBytes;

  RulesetIdentity(
    const std::string& identityRulesetId,
    const std::string& identitySemanticVersion,
    const std::string& identityDescriptorSha256,
    const std::string& identityCanonicalDescriptorBytes
  );
};

#endif // GAME_RULESETIDENTITY_H_
