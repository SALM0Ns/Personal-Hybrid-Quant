// Read-only MT5 completed-candle exporter. No order or position operations.
// Install and run manually only after reviewing source and settings.
#property strict
#property version "1.00"

input int TimerSeconds = 15;       // Polling cadence, seconds
input int RecoveryBars = 256;     // Bounded overlap copied from shift 1

string Symbols[] = {"EURUSDm", "XAUUSDm"};
ENUM_TIMEFRAMES Periods[] = {PERIOD_M15, PERIOD_H1, PERIOD_H4};
string PeriodNames[] = {"M15", "H1", "H4"};
string Root = "mt5_bridge\\incoming\\";
string Server = "";
string Instance = "";
ulong Sequence = 0;
long PreviousTickMsc[2] = {0, 0};
bool TickInitialized[2] = {false, false};
bool TickChanged[2] = {false, false};
ulong TickChangedAt[2] = {0, 0};

string ClockText(const datetime value)
{
   return value > 0 ? TimeToString(value, TIME_DATE | TIME_SECONDS) : "";
}

bool SafeServer(const string value)
{
   int n = StringLen(value);
   if(n < 1 || n > 128) return false;
   for(int i = 0; i < n; i++)
   {
      ushort c = StringGetCharacter(value, i);
      if(!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-'))
         return false;
   }
   return true;
}

// Terminal-attested source metadata only: this is not cryptographic authentication.
bool ApprovedDemoSource()
{
   ResetLastError();
   string current = AccountInfoString(ACCOUNT_SERVER);
   if(GetLastError() != 0 || current != Server || !SafeServer(current)) return false;
   string lower = current;
   if(!StringToLower(lower) || StringFind(lower, "exness") != 0) return false;
   ResetLastError();
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE); // Read-only demo/real mode only.
   return GetLastError() == 0 && mode == ACCOUNT_TRADE_MODE_DEMO;
}

bool BytesOf(const string text, uchar &bytes[])
{
   int count = StringToCharArray(text, bytes, 0, WHOLE_ARRAY, CP_UTF8);
   if(count < 1) return false;
   return ArrayResize(bytes, count - 1) == count - 1; // Exclude terminator.
}

string SHA256(const uchar &bytes[])
{
   uchar key[], digest[];
   ArrayResize(key, 0);
   if(CryptEncode(CRYPT_HASH_SHA256, bytes, key, digest) != 32) return "";
   string result = "";
   for(int i = 0; i < ArraySize(digest); i++)
      result += StringFormat("%02x", (int)digest[i]);
   return result;
}

bool WriteBytes(const string name, const uchar &bytes[])
{
   ResetLastError();
   int handle = FileOpen(name, FILE_WRITE | FILE_BIN);
   if(handle == INVALID_HANDLE)
   {
      PrintFormat("Bridge cannot open output: error %d", GetLastError());
      return false;
   }
   uint written = FileWriteArray(handle, bytes, 0, ArraySize(bytes));
   FileFlush(handle);
   FileClose(handle);
   return written == (uint)ArraySize(bytes);
}

bool PublishText(const string destination, const string text, const bool replace)
{
   uchar bytes[];
   if(!BytesOf(text, bytes)) return false;
   string temporary = destination + ".tmp." + Instance + "." + IntegerToString((long)Sequence);
   if(!WriteBytes(temporary, bytes)) return false;
   // FileMove overwrite visibility/atomicity under Wine is NOT assumed by reader.
   if(!FileMove(temporary, 0, destination, replace ? FILE_REWRITE : 0))
   {
      if(!replace && FileIsExist(destination)) return true;
      PrintFormat("Bridge publication failed: error %d", GetLastError());
      return false;
   }
   return true;
}

void ObserveTick(const int index, MqlTick &tick, bool &available)
{
   available = SymbolInfoTick(Symbols[index], tick) && tick.time > 0 && tick.time_msc > 0;
   if(!available) return;
   if(!TickInitialized[index])
   {
      TickInitialized[index] = true;
      PreviousTickMsc[index] = tick.time_msc; // Initial stored quote proves no freshness.
      return;
   }
   if(tick.time_msc > PreviousTickMsc[index])
   {
      PreviousTickMsc[index] = tick.time_msc;
      TickChanged[index] = true;
      TickChangedAt[index] = GetTickCount64();
   }
   else if(tick.time_msc < PreviousTickMsc[index])
   {
      // Clock regression or source reset: require a new observed update again.
      PreviousTickMsc[index] = tick.time_msc;
      TickChanged[index] = false;
   }
}

void WriteHeartbeat(const int s, const int p, const bool approved, const bool connected,
                    const bool synchronized, const MqlTick &tick, const bool has_tick)
{
   Sequence++;
   string age = TickChanged[s] ? IntegerToString((long)(GetTickCount64() - TickChangedAt[s])) : "";
   string text = "field,value\n" +
      "schema_version,mt5-heartbeat-v1\n" +
      "account_mode," + (approved ? "demo" : "unverified") + "\n" +
      "source_id,exness-mt5\n" +
      "broker_server," + Server + "\n" +
      "symbol," + Symbols[s] + "\n" +
      "timeframe," + PeriodNames[p] + "\n" +
      "instance_id," + Instance + "\n" +
      "sequence," + IntegerToString((long)Sequence) + "\n" +
      "terminal_connected," + (connected ? "1" : "0") + "\n" +
      "series_synchronized," + (synchronized ? "1" : "0") + "\n" +
      "target_tick_time," + (has_tick ? ClockText(tick.time) : "") + "\n" +
      "quote_seen_since_start," + (TickChanged[s] ? "1" : "0") + "\n" +
      "quote_age_ms," + age + "\n" +
      "server_quote_time," + ClockText(TimeCurrent()) + "\n";
   string name = Root + Symbols[s] + "_" + PeriodNames[p] + ".heartbeat.csv";
   if(!PublishText(name, text, true)) Print("Bridge heartbeat not published.");
}

void PublishBars(const int s, const int p)
{
   if(!ApprovedDemoSource()) return;
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   ResetLastError();
   // The currently forming bar (shift 0) is never selected.
   int copied = CopyRates(Symbols[s], Periods[p], 1, RecoveryBars, rates);
   if(copied <= 0)
   {
      PrintFormat("Bridge CopyRates unavailable for %s %s: %d",
                  Symbols[s], PeriodNames[p], GetLastError());
      return;
   }
   // Refuse a batch if the terminal-reported source changed during CopyRates.
   if(!ApprovedDemoSource()) return;
   // A partial CopyRates result is not represented as complete history.
   long digits = SymbolInfoInteger(Symbols[s], SYMBOL_DIGITS);
   if(digits < 0 || digits > 16 || TimeCurrent() <= 0) return;
   string csv = "timestamp,open,high,low,close,tick_volume,spread_points,real_volume\n";
   for(int i = 0; i < copied; i++)
   {
      MqlRates r = rates[i];
      if(r.time <= 0 || (i > 0 && r.time <= rates[i - 1].time))
      {
         Print("Bridge received unordered bar times; refusing publication.");
         return;
      }
      csv += ClockText(r.time) + "," + DoubleToString(r.open, (int)digits) + "," +
         DoubleToString(r.high, (int)digits) + "," + DoubleToString(r.low, (int)digits) + "," +
         DoubleToString(r.close, (int)digits) + "," + IntegerToString(r.tick_volume) + "," +
         IntegerToString(r.spread) + "," + IntegerToString(r.real_volume) + "\n";
   }
   uchar payload[];
   if(!BytesOf(csv, payload)) return;
   string payload_hash = SHA256(payload);
   if(StringLen(payload_hash) != 64) return;
   string identity = "mt5-live-v1\n" + Server + "\n" + Symbols[s] + "\n" +
                     PeriodNames[p] + "\n" + payload_hash + "\n";
   uchar identity_bytes[];
   if(!BytesOf(identity, identity_bytes)) return;
   string batch_id = SHA256(identity_bytes);
   if(StringLen(batch_id) != 64) return;
   string filename = batch_id + ".csv";
   string path = Root + filename;
   string manifest_path = Root + batch_id + ".manifest.csv";
   // Content-addressed files are immutable. Never overwrite an existing payload.
   if(!ApprovedDemoSource()) return;
   if(!FileIsExist(path) && !PublishText(path, csv, false)) return;
   if(FileIsExist(manifest_path) || !ApprovedDemoSource()) return;
   string manifest = "field,value\n" +
      "schema_version,mt5-live-v1\n" +
      "account_mode,demo\n" +
      "batch_id," + batch_id + "\n" +
      "payload_filename," + filename + "\n" +
      "payload_sha256," + payload_hash + "\n" +
      "broker_server," + Server + "\n" +
      "source_id,exness-mt5\n" +
      "symbol," + Symbols[s] + "\n" +
      "timeframe," + PeriodNames[p] + "\n" +
      "row_count," + IntegerToString(copied) + "\n" +
      "exported_at_server," + ClockText(TimeCurrent()) + "\n" +
      "series_synchronized,1\n" +
      "copy_start_shift,1\n" +
      "requested_bars," + IntegerToString(RecoveryBars) + "\n" +
      "copyrates_returned," + IntegerToString(copied) + "\n" +
      "timestamp_semantics,broker_server_clock_unverified\n";
   if(!PublishText(manifest_path, manifest, false))
      Print("Bridge manifest not published; payload remains uncommitted.");
}

int OnInit()
{
   if(TimerSeconds < 5 || TimerSeconds > 3600 || RecoveryBars < 1 || RecoveryBars > 4096)
      return INIT_PARAMETERS_INCORRECT;
   Server = AccountInfoString(ACCOUNT_SERVER); // Server identifier only; no credentials.
   if(!SafeServer(Server) || !ApprovedDemoSource())
   {
      Print("Bridge requires a terminal-attested Exness demo source; account data not authenticated.");
      return INIT_FAILED;
   }
   Instance = IntegerToString((long)TimeLocal()) + "-" + IntegerToString((long)GetTickCount64());
   if(!FolderCreate("mt5_bridge") || !FolderCreate("mt5_bridge\\incoming"))
   {
      PrintFormat("Bridge handoff folder unavailable: %d", GetLastError());
      return INIT_FAILED;
   }
   for(int s = 0; s < ArraySize(Symbols); s++)
      if(!SymbolSelect(Symbols[s], true))
         PrintFormat("Bridge symbol unavailable: %s", Symbols[s]);
   if(!EventSetTimer(TimerSeconds)) return INIT_FAILED;
   OnTimer();
   Print("Read-only candle bridge started; no orders are sent.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   bool connected = (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   bool approved = ApprovedDemoSource();
   for(int s = 0; s < ArraySize(Symbols); s++)
   {
      MqlTick tick;
      bool has_tick = false;
      if(approved) ObserveTick(s, tick, has_tick);
      else
      {
         // Reset tick evidence and prevent publishing after account/server changes.
         TickInitialized[s] = false;
         TickChanged[s] = false;
      }
      for(int p = 0; p < ArraySize(Periods); p++)
      {
         bool synced = approved && connected && SymbolIsSynchronized(Symbols[s]) &&
                       (bool)SeriesInfoInteger(Symbols[s], Periods[p], SERIES_SYNCHRONIZED);
         WriteHeartbeat(s, p, approved, connected, synced, tick, has_tick);
         if(synced) PublishBars(s, p);
      }
   }
}
