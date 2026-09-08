import { describe, expect, it } from "vitest";

import { isAdmin, roleFromClaims, ROLE_CLAIM } from "@/lib/roles";

describe("roleFromClaims", () => {
  it("reads the role from the namespaced cci claim", () => {
    expect(roleFromClaims({ [ROLE_CLAIM]: "admin" })).toBe("admin");
    expect(roleFromClaims({ [ROLE_CLAIM]: "reviewer" })).toBe("reviewer");
  });

  it("returns null when the claim is missing (role not yet assigned)", () => {
    expect(roleFromClaims({})).toBeNull();
    expect(roleFromClaims(undefined)).toBeNull();
  });

  it("returns null for values outside admin/reviewer", () => {
    expect(roleFromClaims({ [ROLE_CLAIM]: "superuser" })).toBeNull();
  });
});

describe("isAdmin", () => {
  it("is true only for the admin role", () => {
    expect(isAdmin({ [ROLE_CLAIM]: "admin" })).toBe(true);
    expect(isAdmin({ [ROLE_CLAIM]: "reviewer" })).toBe(false);
    expect(isAdmin(undefined)).toBe(false);
  });
});
