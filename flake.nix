{
  description = "Discord bot flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.simpleFlake {
      inherit self nixpkgs;
      name = "palbuild";

      shell = { pkgs }:
        pkgs.mkShell {
          buildInputs = [
            (pkgs.python3.withPackages (ps: with ps; [
              aiosqlite
              async-lru
              beautifulsoup4
              discordpy
              lxml
              python-dotenv
              watchfiles
            ]))
          ];
        };
    };
}
