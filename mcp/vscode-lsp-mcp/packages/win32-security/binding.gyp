{
  "targets": [
    {
      "target_name": "win32_security",
      "sources": [
        "native/addon.cc"
      ],
      "libraries": [
        "Advapi32.lib",
        "Shell32.lib",
        "Ole32.lib"
      ],
      "defines": [
        "NAPI_VERSION=8",
        "WIN32_LEAN_AND_MEAN",
        "NOMINMAX",
        "_WIN32_WINNT=0x0A00"
      ],
      "conditions": [
        [
          "OS=='win'",
          {
            "defines": [
              "UNICODE",
              "_UNICODE"
            ],
            "msvs_settings": {
              "VCCLCompilerTool": {
                "AdditionalOptions": [
                  "/permissive-",
                  "/Brepro"
                ],
                "DebugInformationFormat": 0,
                "ExceptionHandling": 0,
                "WarningLevel": 4
              },
              "VCLinkerTool": {
                "AdditionalOptions": [
                  "/Brepro"
                ],
                "GenerateDebugInformation": "false"
              }
            }
          }
        ]
      ]
    }
  ]
}
