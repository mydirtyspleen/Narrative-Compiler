import { useState } from "react";
import { 
  useRenderApiV1RenderPost, 
  useHealthCheck, 
  useUsageApiV1UsageGet 
} from "@workspace/api-client-react";
import type { GameEvent, EventType } from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from "@/components/ui/select";
import { 
  Plus, 
  Trash2, 
  Play, 
  Activity, 
  Zap, 
  Target, 
  AlertCircle,
  Terminal,
  History,
  Info
} from "lucide-react";
import { 
  LineChart, 
  Line, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer 
} from "recharts";

const EVENT_TYPES: EventType[] = [
  "combat", "politics", "economy", "ecology", "social", "weather", "exploration"
];

export function Dashboard() {
  const [events, setEvents] = useState<GameEvent[]>([
    {
      id: "evt-001",
      type: "combat",
      intensity: 0.85,
      actors: ["Northern Legion", "Iron Pact"],
      tags: ["war", "conflict"],
      payload: {}
    }
  ]);

  const [newEvent, setNewEvent] = useState<Partial<GameEvent>>({
    type: "combat",
    intensity: 0.5,
    actors: [],
    tags: []
  });

  const [actorInput, setActorInput] = useState("");
  const [tagInput, setTagInput] = useState("");

  const { data: health } = useHealthCheck();
  const { data: usage } = useUsageApiV1UsageGet();
  
  const renderMutation = useRenderApiV1RenderPost();

  const addEvent = () => {
    if (!newEvent.type || newEvent.intensity === undefined) return;
    
    const event: GameEvent = {
      id: `evt-${Date.now()}`,
      type: newEvent.type as EventType,
      intensity: newEvent.intensity,
      actors: newEvent.actors || [],
      tags: newEvent.tags || [],
      payload: {}
    };

    setEvents([...events, event]);
    setNewEvent({
      type: "combat",
      intensity: 0.5,
      actors: [],
      tags: []
    });
  };

  const removeEvent = (id: string) => {
    setEvents(events.filter(e => e.id !== id));
  };

  const handleRender = () => {
    renderMutation.mutate({
      data: {
        session_id: `session-${Date.now()}`,
        events
      }
    });
  };

  const addActor = () => {
    if (!actorInput.trim()) return;
    setNewEvent(prev => ({
      ...prev,
      actors: [...(prev.actors || []), actorInput.trim()]
    }));
    setActorInput("");
  };

  const addTag = () => {
    if (!tagInput.trim()) return;
    setNewEvent(prev => ({
      ...prev,
      tags: [...(prev.tags || []), tagInput.trim()]
    }));
    setTagInput("");
  };

  const chartData = renderMutation.data?.tension_curve.map((val, i) => ({
    name: `E${i+1}`,
    tension: val
  })) || [];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-50 p-6 font-sans">
      <header className="flex items-center justify-between mb-8 pb-6 border-b border-slate-800">
        <div>
          <h1 className="text-3xl font-bold tracking-tighter flex items-center gap-2">
            <Zap className="text-yellow-500 fill-yellow-500" />
            ADM-API DASHBOARD
          </h1>
          <p className="text-slate-400">Deterministic Narrative Compiler Infrastructure</p>
        </div>
        
        <div className="flex items-center gap-4">
          <div className="flex flex-col items-end">
            <Badge variant={health?.status === "ok" ? "default" : "destructive"} className="mb-1">
              <Activity className="w-3 h-3 mr-1" />
              SYSTEM: {health?.status?.toUpperCase() || "OFFLINE"}
            </Badge>
            <span className="text-xs text-slate-500">
              API Usage: {usage?.requests_today} / {usage?.rate_limit}
            </span>
          </div>
        </div>
      </header>

      <div className="grid grid-cols-12 gap-6">
        {/* Left Column: Event Configuration */}
        <div className="col-span-12 lg:col-span-4 space-y-6">
          <Card className="bg-slate-900 border-slate-800 text-slate-50">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Plus className="w-5 h-5 text-blue-400" />
                Ingest Events
              </CardTitle>
              <CardDescription className="text-slate-400">
                Define typed simulation events for the pipeline
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Event Type</Label>
                <Select 
                  value={newEvent.type} 
                  onValueChange={(v) => setNewEvent({...newEvent, type: v as EventType})}
                >
                  <SelectTrigger className="bg-slate-950 border-slate-800">
                    <SelectValue placeholder="Select type" />
                  </SelectTrigger>
                  <SelectContent className="bg-slate-900 border-slate-800 text-slate-50">
                    {EVENT_TYPES.map(t => (
                      <SelectItem key={t} value={t} className="capitalize">{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <div className="flex justify-between">
                  <Label>Intensity</Label>
                  <span className="text-xs font-mono text-blue-400">{newEvent.intensity?.toFixed(2)}</span>
                </div>
                <Slider 
                  value={[newEvent.intensity || 0]} 
                  min={0} 
                  max={1} 
                  step={0.01}
                  onValueChange={([v]) => setNewEvent({...newEvent, intensity: v})}
                  className="py-4"
                />
              </div>

              <div className="space-y-2">
                <Label>Actors</Label>
                <div className="flex gap-2">
                  <Input 
                    value={actorInput}
                    onChange={(e) => setActorInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && addActor()}
                    placeholder="e.g. Iron Pact"
                    className="bg-slate-950 border-slate-800"
                  />
                  <Button onClick={addActor} size="icon" variant="secondary">
                    <Plus className="w-4 h-4" />
                  </Button>
                </div>
                <div className="flex flex-wrap gap-1 mt-2">
                  {newEvent.actors?.map(a => (
                    <Badge key={a} variant="outline" className="bg-slate-800 border-slate-700">
                      {a}
                    </Badge>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <Label>Tags</Label>
                <div className="flex gap-2">
                  <Input 
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && addTag()}
                    placeholder="e.g. war"
                    className="bg-slate-950 border-slate-800"
                  />
                  <Button onClick={addTag} size="icon" variant="secondary">
                    <Plus className="w-4 h-4" />
                  </Button>
                </div>
                <div className="flex flex-wrap gap-1 mt-2">
                  {newEvent.tags?.map(t => (
                    <Badge key={t} variant="secondary" className="bg-slate-800 text-slate-300">
                      {t}
                    </Badge>
                  ))}
                </div>
              </div>

              <Button onClick={addEvent} className="w-full bg-blue-600 hover:bg-blue-500 mt-4">
                Add Event to Batch
              </Button>
            </CardContent>
          </Card>

          <Card className="bg-slate-900 border-slate-800 text-slate-50">
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <History className="w-4 h-4 text-slate-400" />
                Current Batch ({events.length})
              </CardTitle>
              <Button 
                variant="ghost" 
                size="sm" 
                onClick={() => setEvents([])}
                className="text-xs text-red-400 hover:text-red-300 hover:bg-red-900/20"
              >
                Clear
              </Button>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-[300px] pr-4">
                <div className="space-y-3">
                  {events.map((e) => (
                    <div key={e.id} className="p-3 rounded-lg bg-slate-950 border border-slate-800 group relative">
                      <div className="flex justify-between items-start mb-1">
                        <Badge className="capitalize font-mono text-[10px] py-0">{e.type}</Badge>
                        <Button 
                          variant="ghost" 
                          size="icon" 
                          onClick={() => removeEvent(e.id)}
                          className="w-6 h-6 opacity-0 group-hover:opacity-100 transition-opacity text-red-500"
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                      <div className="text-xs text-slate-400 mb-2">
                        ID: {e.id} | Intensity: {e.intensity.toFixed(2)}
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {e.actors.map(a => <span key={a} className="text-[10px] text-blue-400">@{a}</span>)}
                        {e.tags.map(t => <span key={t} className="text-[10px] text-slate-500">#{t}</span>)}
                      </div>
                    </div>
                  ))}
                  {events.length === 0 && (
                    <div className="text-center py-8 text-slate-600 text-sm">
                      No events in batch
                    </div>
                  )}
                </div>
              </ScrollArea>
              <Button 
                onClick={handleRender} 
                disabled={events.length === 0 || renderMutation.isPending}
                className="w-full bg-green-600 hover:bg-green-500 mt-4 h-12 text-lg font-bold"
              >
                {renderMutation.isPending ? "COMPILING..." : (
                  <><Play className="w-5 h-5 mr-2 fill-current" /> RENDER NARRATIVE</>
                )}
              </Button>
            </CardContent>
          </Card>
        </div>

        {/* Right Column: Narrative Output & Analytics */}
        <div className="col-span-12 lg:col-span-8 space-y-6">
          <Tabs defaultValue="output" className="w-full">
            <TabsList className="bg-slate-900 border border-slate-800 p-1 mb-6">
              <TabsTrigger value="output" className="data-[state=active]:bg-slate-800">
                <Terminal className="w-4 h-4 mr-2" />
                Narrative Output
              </TabsTrigger>
              <TabsTrigger value="analytics" className="data-[state=active]:bg-slate-800">
                <BarChart3 className="w-4 h-4 mr-2" />
                Deterministic Analytics
              </TabsTrigger>
              <TabsTrigger value="raw" className="data-[state=active]:bg-slate-800">
                <Info className="w-4 h-4 mr-2" />
                Raw State Pack
              </TabsTrigger>
            </TabsList>

            <TabsContent value="output" className="space-y-6">
              {!renderMutation.data ? (
                <div className="h-[600px] border-2 border-dashed border-slate-800 rounded-xl flex flex-col items-center justify-center text-slate-600">
                  <Play className="w-12 h-12 mb-4 opacity-20" />
                  <p>Compile a batch of events to see the narrative state</p>
                </div>
              ) : (
                <>
                  <Card className="bg-slate-900 border-slate-800 text-slate-50 overflow-hidden">
                    <div className="bg-blue-600/10 border-b border-blue-900/50 p-4 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Target className="w-5 h-5 text-blue-400" />
                        <span className="font-bold text-blue-400">SCENE SUMMARY</span>
                      </div>
                      <Badge variant="outline" className="bg-blue-900/20 text-blue-300 border-blue-800">
                        Focus: {renderMutation.data.character_focus || "N/A"}
                      </Badge>
                    </div>
                    <CardContent className="p-8">
                      <h2 className="text-3xl font-serif font-bold italic leading-tight text-slate-100">
                        "{renderMutation.data.scene_summary}"
                      </h2>
                    </CardContent>
                  </Card>

                  <Card className="bg-slate-900 border-slate-800 text-slate-50">
                    <CardHeader>
                      <CardTitle className="text-slate-400 text-sm font-mono flex items-center gap-2">
                        <Activity className="w-4 h-4" />
                        CINEMATIC DESCRIPTION
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <p className="text-xl leading-relaxed text-slate-300 font-serif">
                        {renderMutation.data.cinematic_description}
                      </p>
                    </CardContent>
                  </Card>

                  <div className="grid grid-cols-2 gap-6">
                    <Card className="bg-slate-900 border-slate-800 text-slate-50">
                      <CardHeader>
                        <CardTitle className="text-sm font-mono text-orange-400">NARRATIVE CONSEQUENCES</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <ul className="space-y-3">
                          {renderMutation.data.narrative_consequences.map((c, i) => (
                            <li key={i} className="flex gap-3 text-sm text-slate-300">
                              <span className="text-orange-600 font-bold shrink-0">[{i+1}]</span>
                              {c}
                            </li>
                          ))}
                        </ul>
                      </CardContent>
                    </Card>

                    <Card className="bg-slate-900 border-slate-800 text-slate-50">
                      <CardHeader>
                        <CardTitle className="text-sm font-mono text-purple-400">SUGGESTED NEXT EVENTS</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <ul className="space-y-3">
                          {renderMutation.data.suggested_next_events.map((e, i) => (
                            <li key={i} className="flex flex-col gap-1">
                              <div className="flex justify-between items-center">
                                <Badge variant="outline" className="capitalize text-[10px] py-0 border-purple-800 text-purple-300">
                                  {e.type}
                                </Badge>
                                <span className="text-[10px] font-mono text-slate-500">I: {e.intensity.toFixed(2)}</span>
                              </div>
                              <p className="text-xs text-slate-400">{e.description}</p>
                            </li>
                          ))}
                        </ul>
                      </CardContent>
                    </Card>
                  </div>
                </>
              )}
            </TabsContent>

            <TabsContent value="analytics" className="space-y-6">
               <Card className="bg-slate-900 border-slate-800 text-slate-50">
                <CardHeader>
                  <CardTitle>Deterministic Tension Curve</CardTitle>
                  <CardDescription>Mathematical derivation of scene intensity over time</CardDescription>
                </CardHeader>
                <CardContent className="h-[400px]">
                  {chartData.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                        <XAxis dataKey="name" stroke="#64748b" />
                        <YAxis domain={[0, 1]} stroke="#64748b" />
                        <Tooltip 
                          contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1e293b' }}
                          itemStyle={{ color: '#3b82f6' }}
                        />
                        <Line 
                          type="monotone" 
                          dataKey="tension" 
                          stroke="#3b82f6" 
                          strokeWidth={3}
                          dot={{ fill: '#3b82f6', r: 6 }}
                          activeDot={{ r: 8 }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-full flex items-center justify-center text-slate-600 italic">
                      No analytics data available. Render a scene to see the curve.
                    </div>
                  )}
                </CardContent>
              </Card>

              <div className="grid grid-cols-3 gap-6">
                <Card className="bg-slate-900 border-slate-800 text-slate-50">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-xs text-slate-500">AVG INTENSITY</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="text-2xl font-bold">{renderMutation.data?.metadata.avg_intensity.toFixed(3) || "0.000"}</div>
                  </CardContent>
                </Card>
                <Card className="bg-slate-900 border-slate-800 text-slate-50">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-xs text-slate-500">DOMINANT CATEGORY</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="text-2xl font-bold capitalize">{renderMutation.data?.metadata.dominant_category || "None"}</div>
                  </CardContent>
                </Card>
                <Card className="bg-slate-900 border-slate-800 text-slate-50">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-xs text-slate-500">EVENT COUNT</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="text-2xl font-bold">{renderMutation.data?.metadata.event_count || "0"}</div>
                  </CardContent>
                </Card>
              </div>
            </TabsContent>

            <TabsContent value="raw">
              <Card className="bg-slate-900 border-slate-800 text-slate-50">
                <CardContent className="p-0">
                  <pre className="p-6 text-xs font-mono text-blue-300 overflow-auto max-h-[600px]">
                    {JSON.stringify(renderMutation.data, null, 2)}
                  </pre>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          <Card className="bg-slate-900 border-slate-800 text-slate-50 border-l-4 border-l-yellow-600">
            <CardContent className="p-4 flex gap-4">
              <div className="bg-yellow-900/20 p-2 rounded h-fit">
                <AlertCircle className="w-5 h-5 text-yellow-600" />
              </div>
              <div>
                <h4 className="font-bold text-yellow-600 text-sm">LLM Prompt Block (AI Enrichment)</h4>
                <p className="text-xs text-slate-400 mt-1 mb-3">
                  The compiler is 100% deterministic, but you can pass this block to any LLM for creative enhancement.
                </p>
                <div className="bg-slate-950 p-3 rounded border border-slate-800 text-[10px] font-mono text-slate-500 line-clamp-3">
                  {renderMutation.data?.llm_prompt || "Compile events to generate LLM context..."}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

export default Dashboard;
