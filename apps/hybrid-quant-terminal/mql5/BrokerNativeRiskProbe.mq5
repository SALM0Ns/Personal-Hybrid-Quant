// Hypothetical read-only profit and margin estimates. This script cannot trade.
#property script_show_inputs
#property strict

bool written=true;
void Row(int file,string symbol,string direction,string case_name,string volume,
         string open_price,string close_price,string quote_time,string currency,
         string profit,string profit_status,string margin,string margin_status)
{
   if(FileWrite(file,symbol,direction,case_name,volume,open_price,close_price,
                quote_time,currency,profit,profit_status,margin,margin_status)==0)
      written=false;
}

void Scenario(int file,string symbol,ENUM_ORDER_TYPE side,string case_name,
              double volume,double entry,double close_price,int digits,
              datetime quote_time,string currency)
{
   string direction=side==ORDER_TYPE_BUY?"BUY":"SELL";
   double profit=0.0,margin=0.0;
   ResetLastError();
   bool profit_ok=OrderCalcProfit(side,symbol,volume,entry,close_price,profit);
   int profit_error=GetLastError();
   ResetLastError();
   bool margin_ok=OrderCalcMargin(side,symbol,volume,entry,margin);
   int margin_error=GetLastError();
   Row(file,symbol,direction,case_name,DoubleToString(volume,8),
       DoubleToString(entry,digits),DoubleToString(close_price,digits),
       TimeToString(quote_time,TIME_DATE|TIME_SECONDS),currency,
       profit_ok && MathIsValidNumber(profit)?DoubleToString(profit,8):"",
       profit_ok && MathIsValidNumber(profit)?"observed":"unavailable:"+IntegerToString(profit_error),
       margin_ok && MathIsValidNumber(margin)?DoubleToString(margin,8):"",
       margin_ok && MathIsValidNumber(margin)?"observed":"unavailable:"+IntegerToString(margin_error));
}

void Probe(int file,string symbol,string currency)
{
   long selected=0,digits_value=0;
   double tick_size=0.0,volume=0.0;
   MqlTick tick;
   if(!SymbolInfoInteger(symbol,SYMBOL_SELECT,selected) || selected!=1 ||
      !SymbolIsSynchronized(symbol) ||
      !SymbolInfoInteger(symbol,SYMBOL_DIGITS,digits_value) ||
      !SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_SIZE,tick_size) ||
      !SymbolInfoDouble(symbol,SYMBOL_VOLUME_MIN,volume) ||
      !SymbolInfoTick(symbol,tick) || tick.time<=0 ||
      !MathIsValidNumber(tick.bid) || !MathIsValidNumber(tick.ask) ||
      !MathIsValidNumber(tick_size) || !MathIsValidNumber(volume) ||
      tick.bid<=0 || tick.ask<tick.bid || tick_size<=0 || volume<=0 ||
      digits_value<0 || digits_value>8)
   {
      Row(file,symbol,"","unavailable","","","","",currency,"","unavailable:invalid_inputs","","unavailable:invalid_inputs");
      return;
   }
   int digits=(int)digits_value;
   double distance=100.0*tick_size;
   double buy_stop=NormalizeDouble(tick.ask-distance,digits);
   double buy_target=NormalizeDouble(tick.ask+2.0*distance,digits);
   double sell_stop=NormalizeDouble(tick.bid+distance,digits);
   double sell_target=NormalizeDouble(tick.bid-2.0*distance,digits);
   if(buy_stop<=0 || sell_target<=0 || buy_stop>=tick.ask || sell_target>=tick.bid)
   {
      Row(file,symbol,"","unavailable","","","","",currency,"","unavailable:invalid_prices","","unavailable:invalid_prices");
      return;
   }
   Scenario(file,symbol,ORDER_TYPE_BUY,"stop",volume,tick.ask,buy_stop,digits,tick.time,currency);
   Scenario(file,symbol,ORDER_TYPE_BUY,"target",volume,tick.ask,buy_target,digits,tick.time,currency);
   Scenario(file,symbol,ORDER_TYPE_SELL,"stop",volume,tick.bid,sell_stop,digits,tick.time,currency);
   Scenario(file,symbol,ORDER_TYPE_SELL,"target",volume,tick.bid,sell_target,digits,tick.time,currency);
}

void OnStart()
{
   string server=AccountInfoString(ACCOUNT_SERVER);
   string currency=AccountInfoString(ACCOUNT_CURRENCY);
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO ||
      StringFind(server,"Exness")<0 || !TerminalInfoInteger(TERMINAL_CONNECTED) || currency=="")
   {
      Print("Probe refused: connected Exness demo and account currency required.");
      return;
   }
   string filename="broker_native_probe_"+IntegerToString((long)TimeLocal())+
                   "_"+IntegerToString((long)GetTickCount64())+".csv";
   string temporary=filename+".partial";
   if(FileIsExist(filename) || FileIsExist(temporary)) { Print("Probe destination exists."); return; }
   int file=FileOpen(temporary,FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(file==INVALID_HANDLE) { Print("Probe open failed: ",GetLastError()); return; }
   if(FileWrite(file,"instrument","direction","case","volume","open_price","close_price",
                "quote_broker_time","account_currency","native_profit","profit_status",
                "native_margin","margin_status")==0) written=false;
   Probe(file,"EURUSDm",currency);
   Probe(file,"XAUUSDm",currency);
   FileFlush(file);
   FileClose(file);
   if(!written) { Print("Probe incomplete; partial file: ",temporary); return; }
   if(!FileMove(temporary,0,filename,0)) { Print("Probe publish failed: ",GetLastError()); return; }
   Print("Hypothetical read-only native probe saved in MQL5/Files: ",filename,
         "; broker clock and source authentication remain unverified.");
}
