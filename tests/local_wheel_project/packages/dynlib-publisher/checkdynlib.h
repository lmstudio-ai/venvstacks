#ifdef _WIN32
#ifdef CHECK_DYNLIB_EXPORTS
#define CHECK_DYNLIB_API __declspec(dllexport)
#else
#define CHECK_DYNLIB_API __declspec(dllimport)
#endif
#else
#define CHECK_DYNLIB_API
#endif

CHECK_DYNLIB_API int sum(int a, int b);
